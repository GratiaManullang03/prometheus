"""Telegram bot interface for human-agent communication.

Sends structured proposals and waits for operator approval.
Uses long-polling — no webhook server required.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/{method}"
_POLL_TIMEOUT = 30
_RETRY_DELAY = 5


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass
class ApprovalRequest:
    """An approval request sent to the operator."""

    request_id: str
    proposal: str
    reason: str
    expected_benefit: str
    risk_analysis: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    operator_comment: str = ""


class TelegramBot:
    """Sends messages and manages approval callbacks via Telegram.

    Args:
        token: Telegram bot token.
        chat_id: Operator's Telegram chat ID.
    """

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._last_update_id: int = 0
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._status_provider: Optional[Callable[[], str]] = None
        self._chat_handler: Optional[Callable[[str], str]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_polling(self) -> None:
        """Start background long-polling thread."""
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="telegram-poller"
        )
        self._poll_thread.start()
        logger.info("TelegramBot: polling started")

    def stop_polling(self) -> None:
        """Stop the polling thread."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=10)
        logger.info("TelegramBot: polling stopped")

    def send_message(self, text: str) -> bool:
        """Send a plain text message to the operator."""
        return self._api_call("sendMessage", {"chat_id": self._chat_id, "text": text[:4096]})

    def send_approval_request(self, request: ApprovalRequest) -> bool:
        """Format and send an approval request with inline keyboard."""
        text = self._format_proposal(request)
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{request.request_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{request.request_id}"},
            ]]
        }
        payload = {
            "chat_id": self._chat_id,
            "text": text[:4096],
            "reply_markup": keyboard,
            "parse_mode": "Markdown",
        }
        with self._lock:
            self._pending[request.request_id] = request
        success = self._api_call("sendMessage", payload)
        logger.info("TelegramBot: sent approval request %s", request.request_id)
        return success

    def register_callback(self, request_id: str, on_decision: Callable[[ApprovalStatus], None]) -> None:
        """Register a callback for when a decision arrives."""
        with self._lock:
            req = self._pending.get(request_id)
            if req:
                req._callback = on_decision  # type: ignore[attr-defined]

    def set_status_provider(self, provider: Callable[[], str]) -> None:
        """Register a callable that returns a formatted agent status string."""
        self._status_provider = provider

    def set_chat_handler(self, handler: Callable[[str], str]) -> None:
        """Register a callable that handles free-form operator questions.

        Args:
            handler: Takes operator message, returns response string.
        """
        self._chat_handler = handler

    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Long-polling loop — runs in background thread."""
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as exc:
                logger.warning("TelegramBot: poll error: %s", exc)
                time.sleep(_RETRY_DELAY)

    def _get_updates(self) -> list[dict]:
        """Fetch new updates via long-poll."""
        # POST + JSON body agar allowed_updates dikirim sebagai array JSON
        # (GET dengan repeated params tidak di-parse Telegram sebagai array)
        payload = {
            "offset": self._last_update_id + 1,
            "timeout": _POLL_TIMEOUT,
            "allowed_updates": ["callback_query", "message"],
        }
        url = _BASE_URL.format(token=self._token, method="getUpdates")
        try:
            with httpx.Client(timeout=_POLL_TIMEOUT + 5) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                updates = data.get("result", [])
                if updates:
                    self._last_update_id = updates[-1]["update_id"]
                return updates
        except Exception as exc:
            logger.debug("TelegramBot: getUpdates error: %s", exc)
            return []

    def _handle_update(self, update: dict) -> None:
        """Dispatch update to appropriate handler."""
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update:
            self._handle_message(update["message"])

    def _handle_message(self, message: dict) -> None:
        """Handle plain text messages and commands from the operator."""
        sender_id = str(message.get("from", {}).get("id", ""))
        if sender_id != str(self._chat_id):
            logger.warning("TelegramBot: unauthorized message from user %s — ignored", sender_id)
            return

        text = message.get("text", "").strip()
        if not text:
            return

        if text.startswith("/status") or text.lower() == "status":
            self._send_status()
        elif text.startswith("/help"):
            self.send_message(
                "Perintah tersedia:\n"
                "/status — lihat kondisi agen\n"
                "/help — tampilkan bantuan ini\n\n"
                "Atau ketik pertanyaan apa saja dan saya akan menjawabnya."
            )
        else:
            self._handle_chat(text)

    def _handle_chat(self, text: str) -> None:
        """Handle free-form question using registered chat handler."""
        if self._chat_handler is None:
            self._send_status()
            return
        try:
            response = self._chat_handler(text)
            self.send_message(response)
        except Exception as exc:
            logger.error("TelegramBot: chat handler failed: %s", exc)
            self.send_message("Maaf, gagal memproses pertanyaanmu saat ini.")

    def _send_status(self) -> None:
        """Send current agent status to operator."""
        if self._status_provider is None:
            self.send_message("Status provider belum terdaftar.")
            return
        try:
            status_text = self._status_provider()
            self.send_message(status_text)
        except Exception as exc:
            logger.error("TelegramBot: gagal ambil status: %s", exc)
            self.send_message("Gagal mengambil status agen.")

    def _handle_callback(self, callback: dict) -> None:
        """Process inline keyboard callback (approve/reject)."""
        sender_id = str(callback.get("from", {}).get("id", ""))
        if sender_id != str(self._chat_id):
            logger.warning("TelegramBot: unauthorized callback from user %s — ignored", sender_id)
            return

        data: str = callback.get("data", "")
        if not data:
            return
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        action, request_id = parts

        with self._lock:
            req = self._pending.get(request_id)
            if req is None:
                return
            if action == "approve":
                req.status = ApprovalStatus.APPROVED
            elif action == "reject":
                req.status = ApprovalStatus.REJECTED
            else:
                return
            cb = getattr(req, "_callback", None)
            del self._pending[request_id]

        self._answer_callback(callback.get("id", ""))
        self.send_message(
            f"Decision recorded: *{req.status.value.upper()}* for request `{request_id[:8]}`"
        )
        logger.info("TelegramBot: %s -> %s", request_id[:8], req.status.value)
        if cb:
            cb(req.status)

    def _answer_callback(self, callback_id: str) -> None:
        self._api_call("answerCallbackQuery", {"callback_query_id": callback_id})

    def _api_call(self, method: str, payload: dict) -> bool:
        url = _BASE_URL.format(token=self._token, method=method)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.error("TelegramBot: %s failed: %s", method, exc)
            return False

    @staticmethod
    def _format_proposal(req: ApprovalRequest) -> str:
        return (
            f"*PROMETHEUS — Approval Required*\n\n"
            f"*ID:* `{req.request_id[:8]}`\n"
            f"*Proposal:* {req.proposal}\n\n"
            f"*Reason:* {req.reason}\n\n"
            f"*Expected Benefit:* {req.expected_benefit}\n\n"
            f"*Risk Analysis:* {req.risk_analysis}\n\n"
            f"Please approve or reject this change."
        )
