"""Browser agent — web research and page interaction.

Uses Playwright (headless Chromium) when available.
Falls back to plain httpx for all operations when Playwright is not installed.

Capabilities:
  research()  — DDG search + content fetch (feeds Brain context)
  fetch_url() — fetch a single page's text content
  interact()  — click/fill/navigate for Phase 2 economic actions
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("./.cache/browser")
_CACHE_TTL = 3600
_PW_TIMEOUT = 15_000  # ms


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class ResearchResult:
    query: str
    search_results: list[SearchResult]
    fetched_content: dict[str, str]
    summary: str
    cached: bool = False


class BrowserAgent:
    """Web research and interaction agent.

    Prefers Playwright (real browser, JS support) when installed.
    Falls back to httpx (fast, lightweight) when Playwright is unavailable.

    Args:
        headless: Run browser without visible UI (default True).
        cache_dir: Directory for caching research results (1h TTL).
        serp_api_key: Unused — kept for backward compatibility.
    """

    def __init__(
        self,
        headless: bool = True,
        cache_dir: Optional[Path] = None,
        serp_api_key: Optional[str] = None,
    ) -> None:
        self._headless = headless
        self._cache_dir = (cache_dir or _CACHE_DIR).resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pw_ok = _check_playwright()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def research(self, query: str, max_results: int = 5) -> ResearchResult:
        """Search for query and fetch content from top results."""
        key = hashlib.sha256(query.encode()).hexdigest()
        cached = self._load_cache(key)
        if cached:
            logger.info("BrowserAgent: cache hit for %r", query[:60])
            return ResearchResult(**cached, cached=True)

        logger.info("BrowserAgent: researching %r", query[:60])
        results = self._search(query, max_results)

        fetched: dict[str, str] = {}
        for item in results[:3]:
            content = self._fetch_page(item.url)
            if content:
                fetched[item.url] = content

        summary = (
            f"Research for '{query}':\n"
            + "\n".join(f"- {r.title}: {r.snippet}" for r in results[:5])
            + f"\n[{len(fetched)} pages fetched]"
        )
        result = ResearchResult(
            query=query,
            search_results=results,
            fetched_content=fetched,
            summary=summary,
        )
        self._save_cache(key, result)
        return result

    def fetch_url(self, url: str) -> str:
        """Fetch and return text content from a URL."""
        return self._fetch_page(url) or ""

    def interact(self, url: str, actions: list[dict]) -> str:
        """Execute browser actions and return final page text content.

        Requires Playwright. Used for economic agency tasks (Phase 2+).

        Args:
            url: Starting URL.
            actions: Sequence of action dicts:
                     {type: click|fill|navigate|wait, selector: str, value: str}

        Returns:
            Text content of the final page state.
        """
        if not self._pw_ok:
            raise RuntimeError(
                "Playwright required for interact() — run: playwright install chromium"
            )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._headless)
            page = browser.new_page()
            try:
                page.goto(url, timeout=_PW_TIMEOUT)
                for action in actions:
                    _execute_action(page, action)
                return page.inner_text("body")[:50_000]
            finally:
                browser.close()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self, query: str, limit: int) -> list[SearchResult]:
        if self._pw_ok:
            results = self._pw_search(query, limit)
            if results:
                return results
        return self._httpx_search(query, limit)

    def _pw_search(self, query: str, limit: int) -> list[SearchResult]:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=self._headless)
                page = browser.new_page()
                try:
                    page.goto(
                        f"https://html.duckduckgo.com/html/?q={query}",
                        timeout=_PW_TIMEOUT,
                    )
                    results = []
                    for item in page.query_selector_all(".result")[:limit]:
                        title_el = item.query_selector(".result__a")
                        snip_el = item.query_selector(".result__snippet")
                        title = title_el.inner_text() if title_el else ""
                        url = title_el.get_attribute("href") if title_el else ""
                        snip = snip_el.inner_text() if snip_el else ""
                        if title and url:
                            results.append(SearchResult(title=title, url=url, snippet=snip))
                    logger.info("BrowserAgent: Playwright DDG returned %d results", len(results))
                    return results
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning("BrowserAgent: Playwright search failed: %s", exc)
            return []

    def _httpx_search(self, query: str, limit: int) -> list[SearchResult]:
        try:
            with httpx.Client(
                timeout=15.0,
                headers={
                    "User-Agent": "PrometheusAgent/1.0",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
            ) as client:
                resp = client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query, "kl": "us-en"},
                )
                resp.raise_for_status()
                results = _parse_ddg_html(resp.text, limit)
                logger.info("BrowserAgent: httpx DDG returned %d results", len(results))
                return results
        except Exception as exc:
            logger.error("BrowserAgent: httpx search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch_page(self, url: str) -> Optional[str]:
        if not url.startswith(("http://", "https://")):
            return None
        if self._pw_ok:
            content = self._pw_fetch(url)
            if content:
                return content
        return self._httpx_fetch(url)

    def _pw_fetch(self, url: str) -> Optional[str]:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=self._headless)
                page = browser.new_page()
                try:
                    page.goto(url, timeout=_PW_TIMEOUT, wait_until="domcontentloaded")
                    return page.inner_text("body")[:50_000]
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning("BrowserAgent: Playwright fetch failed %s: %s", url[:60], exc)
            return None

    def _httpx_fetch(self, url: str) -> Optional[str]:
        try:
            with httpx.Client(
                timeout=15.0,
                headers={"User-Agent": "PrometheusAgent/1.0"},
                follow_redirects=True,
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text[:50_000]
        except Exception as exc:
            logger.warning("BrowserAgent: httpx fetch failed %s: %s", url[:60], exc)
            return None

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _load_cache(self, key: str) -> Optional[dict]:
        path = self._cache_dir / f"{key}.json"
        if not path.exists() or time.time() - path.stat().st_mtime > _CACHE_TTL:
            return None
        try:
            raw = json.loads(path.read_text("utf-8"))
            raw["search_results"] = [SearchResult(**r) for r in raw.get("search_results", [])]
            return raw
        except Exception:
            return None

    def _save_cache(self, key: str, result: ResearchResult) -> None:
        path = self._cache_dir / f"{key}.json"
        path.write_text(
            json.dumps(
                {
                    "query": result.query,
                    "search_results": [vars(r) for r in result.search_results],
                    "fetched_content": result.fetched_content,
                    "summary": result.summary,
                },
                indent=2,
                ensure_ascii=False,
            ),
            "utf-8",
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _check_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        logger.warning(
            "BrowserAgent: playwright not installed — using httpx fallback. "
            "Run: pip install playwright && playwright install chromium"
        )
        return False


def _parse_ddg_html(html: str, limit: int) -> list[SearchResult]:
    results = []
    title_links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
    )
    for i, (url, title) in enumerate(title_links[:limit]):
        snippet = snippets[i] if i < len(snippets) else ""
        results.append(
            SearchResult(
                title=re.sub(r"<[^>]+>", "", title).strip(),
                url=url,
                snippet=re.sub(r"<[^>]+>", "", snippet).strip(),
            )
        )
    return results


def _execute_action(page, action: dict) -> None:
    t = action.get("type", "")
    sel = action.get("selector", "")
    val = action.get("value", "")
    if t == "click":
        page.click(sel)
    elif t == "fill":
        page.fill(sel, val)
    elif t == "navigate":
        page.goto(val)
    elif t == "wait":
        page.wait_for_timeout(int(val) if val else 1000)
