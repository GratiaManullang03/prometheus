"""Human approval gate — blocks agent execution until operator decides.

Enforces the immutable rule: the agent NEVER modifies critical
components without explicit human approval.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from communication.telegram_bot import ApprovalRequest, ApprovalStatus, TelegramBot

logger = logging.getLogger(__name__)


class ApprovalTimeout(Exception):
    """Raised when operator does not respond within the deadline."""


class ApprovalRejected(Exception):
    """Raised when the operator explicitly rejects a proposal."""


@dataclass
class ApprovalContext:
    """Full context for a human approval gate."""

    proposal: str
    reason: str
    expected_benefit: str
    risk_analysis: str
    timeout_seconds: int = 86400


class HumanApprovalGate:
    """Blocks execution and waits for human approval via Telegram.

    If the operator does not respond within `timeout_seconds`,
    the gate times out and the action is NOT taken.

    Args:
        bot: Configured TelegramBot instance.
        default_timeout: How long to wait for approval (seconds).
    """

    def __init__(self, bot: TelegramBot, default_timeout: int = 86400) -> None:
        self._bot = bot
        self._default_timeout = default_timeout

    def request_and_wait(self, context: ApprovalContext) -> ApprovalStatus:
        """Send approval request and block until decision or timeout.

        Args:
            context: Proposal details to send to the operator.

        Returns:
            ApprovalStatus (APPROVED, REJECTED, or TIMED_OUT).

        Raises:
            ApprovalRejected: If operator explicitly rejects.
            ApprovalTimeout: If no response before deadline.
        """
        request_id = str(uuid.uuid4())
        timeout = context.timeout_seconds or self._default_timeout

        req = ApprovalRequest(
            request_id=request_id,
            proposal=context.proposal,
            reason=context.reason,
            expected_benefit=context.expected_benefit,
            risk_analysis=context.risk_analysis,
        )

        decision_event = threading.Event()
        final_status: list[ApprovalStatus] = []

        def on_decision(status: ApprovalStatus) -> None:
            final_status.append(status)
            decision_event.set()

        self._bot.send_approval_request(req)
        self._bot.register_callback(request_id, on_decision)

        logger.info(
            "HumanApprovalGate: waiting for decision on %s (timeout=%ds)",
            request_id[:8],
            timeout,
        )

        got_response = decision_event.wait(timeout=timeout)

        if not got_response:
            logger.warning("HumanApprovalGate: timed out waiting for %s", request_id[:8])
            self._bot.send_message(
                f"Request `{request_id[:8]}` timed out — action was NOT taken."
            )
            raise ApprovalTimeout(f"Approval timed out for request {request_id[:8]}")

        status = final_status[0]
        if status == ApprovalStatus.REJECTED:
            logger.info("HumanApprovalGate: rejected %s", request_id[:8])
            raise ApprovalRejected(f"Operator rejected request {request_id[:8]}")

        logger.info("HumanApprovalGate: approved %s", request_id[:8])
        return status

    def notify(self, message: str) -> None:
        """Send a non-blocking informational message to the operator."""
        self._bot.send_message(message)
        logger.info("HumanApprovalGate: notification sent: %s", message[:80])
