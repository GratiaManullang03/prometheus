"""Browser research agent — internet search and documentation retrieval.

All retrieved content must be validated through Docker testing before use.
This module never executes downloaded code directly.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("./.cache/browser")
_CACHE_TTL = 3600  # 1 hour
_REQUEST_TIMEOUT = 15.0
_MAX_RESPONSE_BYTES = 500_000  # 500 KB


@dataclass
class SearchResult:
    """A single search result item."""

    title: str
    url: str
    snippet: str


@dataclass
class ResearchResult:
    """Aggregated result from a research query."""

    query: str
    search_results: list[SearchResult]
    fetched_content: dict[str, str]
    summary: str
    cached: bool = False


class BrowserAgent:
    """Searches the internet and fetches documentation safely.

    Uses SerpAPI (or DuckDuckGo as fallback) for search and
    plain HTTP GET for content retrieval.

    Args:
        serp_api_key: Optional SerpAPI key for richer results.
        cache_dir: Directory for response caching.
        user_agent: HTTP User-Agent header value.
    """

    def __init__(
        self,
        serp_api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        user_agent: str = "PrometheusResearchAgent/0.1",
    ) -> None:
        self._serp_key = serp_api_key
        self._cache_dir = (cache_dir or _CACHE_DIR).resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._headers = {"User-Agent": user_agent}

    def research(self, query: str, max_results: int = 5) -> ResearchResult:
        """Search for a query and fetch top results.

        Args:
            query: Natural language research question.
            max_results: Maximum number of URLs to fetch.

        Returns:
            ResearchResult containing snippets and fetched content.
        """
        cache_key = self._cache_key(query)
        cached = self._load_cache(cache_key)
        if cached:
            logger.info("BrowserAgent: cache hit for %r", query[:60])
            return ResearchResult(**cached, cached=True)

        logger.info("BrowserAgent: researching %r", query[:60])
        results = self._search(query, max_results)
        fetched: dict[str, str] = {}
        for item in results[:max_results]:
            content = self._fetch_url(item.url)
            if content:
                fetched[item.url] = content

        summary = self._summarise(query, results, fetched)
        research = ResearchResult(
            query=query,
            search_results=results,
            fetched_content=fetched,
            summary=summary,
        )
        self._save_cache(cache_key, research)
        return research

    def fetch_url(self, url: str) -> str:
        """Fetch raw content from a URL.

        Args:
            url: Target URL (http/https only).

        Returns:
            Truncated text content.
        """
        return self._fetch_url(url) or ""

    # ------------------------------------------------------------------

    def _search(self, query: str, limit: int) -> list[SearchResult]:
        if self._serp_key:
            return self._serp_search(query, limit)
        return self._ddg_search(query, limit)

    def _serp_search(self, query: str, limit: int) -> list[SearchResult]:
        """Search via SerpAPI."""
        params = {
            "q": query,
            "num": limit,
            "api_key": self._serp_key,
            "engine": "google",
        }
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT, headers=self._headers) as client:
                resp = client.get("https://serpapi.com/search", params=params)
                resp.raise_for_status()
                data = resp.json()
                return [
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                    )
                    for r in data.get("organic_results", [])[:limit]
                ]
        except Exception as exc:
            logger.warning("SerpAPI search failed: %s — falling back to DDG", exc)
            return self._ddg_search(query, limit)

    def _ddg_search(self, query: str, limit: int) -> list[SearchResult]:
        """Search via DuckDuckGo Lite (no JS)."""
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT, headers=self._headers) as client:
                params = {"q": query, "kl": "us-en"}
                resp = client.get("https://lite.duckduckgo.com/lite/", params=params)
                resp.raise_for_status()
                return self._parse_ddg_html(resp.text, limit)
        except Exception as exc:
            logger.error("DDG search failed: %s", exc)
            return []

    @staticmethod
    def _parse_ddg_html(html: str, limit: int) -> list[SearchResult]:
        """Very simple DDG Lite result extractor."""
        import re
        results: list[SearchResult] = []
        snippets = re.findall(r'class="result-snippet"[^>]*>(.*?)</span>', html, re.DOTALL)
        links = re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>', html)
        for i, (url, title) in enumerate(links[:limit]):
            snippet = snippets[i] if i < len(snippets) else ""
            snippet_clean = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append(SearchResult(title=title.strip(), url=url, snippet=snippet_clean))
        return results

    @staticmethod
    def _is_ssrf_safe(url: str) -> bool:
        """Block requests to private/loopback/link-local addresses (SSRF protection)."""
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except Exception:
            return False
        return True

    def _fetch_url(self, url: str) -> Optional[str]:
        if not url.startswith(("http://", "https://")):
            logger.warning("BrowserAgent: non-http URL blocked: %s", url[:80])
            return None
        if not self._is_ssrf_safe(url):
            logger.warning("BrowserAgent: SSRF blocked for URL: %s", url[:80])
            return None
        try:
            with httpx.Client(
                timeout=_REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                content = resp.text[:_MAX_RESPONSE_BYTES]
                logger.debug("BrowserAgent: fetched %d bytes from %s", len(content), url[:80])
                return content
        except Exception as exc:
            logger.warning("BrowserAgent: failed to fetch %s: %s", url[:80], exc)
            return None

    @staticmethod
    def _summarise(
        query: str, results: list[SearchResult], fetched: dict[str, str]
    ) -> str:
        snippet_block = "\n".join(f"- {r.title}: {r.snippet}" for r in results[:5])
        return f"Research for '{query}':\n{snippet_block}\n[{len(fetched)} pages fetched]"

    def _cache_key(self, query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()

    def _load_cache(self, key: str) -> Optional[dict]:
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > _CACHE_TTL:
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["search_results"] = [SearchResult(**r) for r in raw.get("search_results", [])]
            return raw
        except Exception:
            return None

    def _save_cache(self, key: str, result: ResearchResult) -> None:
        path = self._cache_dir / f"{key}.json"
        data = {
            "query": result.query,
            "search_results": [vars(r) for r in result.search_results],
            "fetched_content": result.fetched_content,
            "summary": result.summary,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
