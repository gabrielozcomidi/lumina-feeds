"""HTTP clients for Lumina Feeds — Yahoo Finance and Google News RSS.

Pure I/O classes — no entity coupling, no coordinator coupling. Each public
method returns a parsed dict/list or raises FeedClientError. The coordinator
layer (coordinator.py) batches and schedules; the entity layer (sensor.py)
just reads from coordinator data.

Why a separate module: before this refactor the sensor classes did their own
HTTP, parsing, error handling, and entity state management. That made every
sensor responsible for retry semantics individually, made testing impossible
without HA, and forced N redundant requests on a config-reload (each sensor
re-fetched even though the data was the same). Splitting this out lets a
single coordinator update once per interval and feed every sensor.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import aiohttp
import feedparser

from .const import GOOGLE_NEWS_RSS_URL, YAHOO_CHART_URL, YAHOO_SEARCH_URL
from .url_safety import is_safe_url, resolve_is_safe

_LOGGER = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

REGION_MAP = {
    "en": "US", "he": "IL", "de": "DE", "fr": "FR",
    "es": "ES", "it": "IT", "pt": "BR", "ja": "JP",
    "ko": "KR", "zh": "CN", "ar": "SA", "ru": "RU",
    "nl": "NL", "sv": "SE", "da": "DK", "no": "NO",
}

CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "ILS": "₪",
    "JPY": "¥", "BTC": "₿", "AUD": "A$", "CAD": "C$",
    "CHF": "Fr", "INR": "₹", "CNY": "¥", "KRW": "₩",
    "HKD": "HK$", "SGD": "S$", "NZD": "NZ$", "SEK": "kr",
    "NOK": "kr", "DKK": "kr", "MXN": "Mex$", "BRL": "R$",
    "ZAR": "R", "TRY": "₺", "RUB": "₽", "PLN": "zł",
}


class FeedClientError(Exception):
    """Raised by client methods on any fetch/parse failure. The coordinator
    converts this into UpdateFailed so HA can mark the entity unavailable."""


# ──────────────────────────────────────────────────────────────────────
# Yahoo Finance
# ──────────────────────────────────────────────────────────────────────


class YahooClient:
    """Wraps the unofficial Yahoo Finance v8 chart API + v1 search API.

    Both endpoints are undocumented and may change without notice. The client
    is conservative: short timeouts, never raises out of fetch_quotes (returns
    a sparse dict so partial outages still deliver data), distinguishes
    network errors (warning) from parse errors (error)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        """Fetch a single quote. Returns the parsed dict or None on any error."""
        try:
            url = YAHOO_CHART_URL.format(symbol=symbol)
            async with self._session.get(
                url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s for stock %s", resp.status, symbol)
                    return None
                data = await resp.json()
        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching stock %s", symbol)
            return None
        except aiohttp.ClientError as err:
            _LOGGER.warning("Lumina Feeds: Network error fetching stock %s: %s", symbol, err)
            return None
        except Exception as err:  # noqa: BLE001 — last-resort guard
            _LOGGER.error("Lumina Feeds: Error fetching stock %s: %s", symbol, err)
            return None

        return _parse_yahoo_quote(symbol, data)

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any] | None]:
        """Fetch many quotes concurrently. Returns {symbol: parsed_or_None}."""
        if not symbols:
            return {}
        results = await asyncio.gather(*(self.fetch_quote(s) for s in symbols))
        return dict(zip(symbols, results))

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Yahoo Finance autocomplete. Used by the config flow."""
        try:
            url = YAHOO_SEARCH_URL.format(query=quote_plus(query))
            async with self._session.get(
                url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: Yahoo search HTTP %s", resp.status)
                    return []
                data = await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Lumina Feeds: Yahoo search error: %s", err)
            return []

        results: list[dict[str, Any]] = []
        for q in data.get("quotes", []):
            qtype = q.get("quoteType", "")
            if qtype not in ("EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY", "MUTUALFUND", "CURRENCY"):
                continue
            results.append({
                "symbol": q.get("symbol", ""),
                "name": q.get("shortname", "") or q.get("longname", "") or q.get("symbol", ""),
                "type": qtype,
                "exchange": q.get("exchDisp", "") or q.get("exchange", ""),
            })
        return results[:8]


def _parse_yahoo_quote(symbol: str, data: dict[str, Any]) -> dict[str, Any] | None:
    chart = data.get("chart", {})
    result = chart.get("result", [])
    if not result:
        error = chart.get("error", {})
        _LOGGER.warning(
            "Lumina Feeds: No data for %s: %s",
            symbol, error.get("description", "unknown") if isinstance(error, dict) else "unknown",
        )
        return None

    meta = result[0].get("meta", {})
    price = meta.get("regularMarketPrice", 0)
    prev_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
    currency = meta.get("currency", "USD")
    name = meta.get("shortName", "") or meta.get("symbol", symbol)

    change = round(price - prev_close, 2) if prev_close else 0
    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

    return {
        "symbol": symbol,
        "short_name": name,
        "price": round(price, 2),
        "regular_market_price": round(price, 2),
        "regular_market_previous_close": round(prev_close, 2),
        "regular_market_change": change,
        "regular_market_change_percent": change_pct,
        "currency": currency,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency, currency),
        "market_state": meta.get("marketState", "CLOSED"),
        "trending": "up" if change >= 0 else "down",
        "exchange": meta.get("exchangeName", ""),
    }


# ──────────────────────────────────────────────────────────────────────
# News RSS (Google News + direct URLs)
# ──────────────────────────────────────────────────────────────────────


class NewsClient:
    """Fetches news via Google News RSS (keyword search) or a direct RSS URL.

    Direct URLs run through the SSRF allow-list (url_safety) at both
    config-flow validation time AND fetch time. Even if a hostile DNS
    answer arrived between validation and fetch, the second check catches it."""

    def __init__(self, hass, session: aiohttp.ClientSession) -> None:
        self._hass = hass
        self._session = session

    async def fetch_keywords(
        self, keywords: str, language: str, max_items: int,
    ) -> list[dict[str, Any]]:
        """Fetch Google News RSS for a comma-separated keyword string."""
        parts = [k.strip() for k in keywords.split(",") if k.strip()]
        query = quote_plus(" OR ".join(parts))
        region = REGION_MAP.get(language, "US")
        url = GOOGLE_NEWS_RSS_URL.format(query=query, lang=language, region=region)
        return await self._fetch_rss(url, max_items, is_google_news=True)

    async def fetch_url(self, url: str, max_items: int) -> list[dict[str, Any]]:
        """Fetch a user-supplied RSS feed. Validates URL safety first."""
        ok, reason = is_safe_url(url)
        if not ok:
            raise FeedClientError(f"unsafe_url:{reason}")
        host = (urlparse(url).hostname or "").lower()
        ok, reason = await resolve_is_safe(self._hass, host)
        if not ok:
            raise FeedClientError(f"unsafe_host:{reason}")
        return await self._fetch_rss(url, max_items, is_google_news=False)

    async def _fetch_rss(
        self, url: str, max_items: int, *, is_google_news: bool,
    ) -> list[dict[str, Any]]:
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise FeedClientError(f"http_{resp.status}")
                text = await resp.text()
        except asyncio.TimeoutError as err:
            raise FeedClientError("timeout") from err
        except aiohttp.ClientError as err:
            raise FeedClientError(f"network:{err}") from err

        feed = await self._hass.async_add_executor_job(feedparser.parse, text)

        entries: list[dict[str, Any]] = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "")
            source = ""

            # Google News titles look like "Real Title - Source Name"; split.
            if is_google_news and " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0]
                source = parts[1] if len(parts) > 1 else ""

            if not is_google_news and not source:
                source = entry.get("author", "") or feed.feed.get("title", "") or ""

            raw_summary = entry.get("summary", "") or entry.get("description", "")
            clean_summary = html.unescape(_HTML_TAG_RE.sub("", raw_summary)).strip()
            if len(clean_summary) > 200:
                clean_summary = clean_summary[:197] + "..."

            entries.append({
                "title": html.unescape(title),
                "source": html.unescape(source),
                "summary": clean_summary,
                "published": entry.get("published", ""),
                "link": entry.get("link", ""),
            })

        return entries


# ──────────────────────────────────────────────────────────────────────
# Interest keying — shared so coordinator + entities agree
# ──────────────────────────────────────────────────────────────────────


def interest_key(interest: dict[str, Any]) -> str:
    """Stable key for a configured interest. Used to index coordinator data
    and to derive the entity unique_id."""
    name = interest.get("name", "news")
    return name.lower().replace(" ", "_").replace("-", "_")
