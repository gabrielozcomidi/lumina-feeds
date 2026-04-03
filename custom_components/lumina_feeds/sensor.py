"""Sensor platform for Lumina Feeds — news interests and stock quotes."""

import logging
import asyncio
from datetime import timedelta
from urllib.parse import quote_plus
from typing import Any

import aiohttp
import feedparser

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_INTERESTS,
    CONF_STOCKS,
    CONF_NEWS_INTERVAL,
    CONF_STOCK_INTERVAL,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_STOCK_INTERVAL,
    GOOGLE_NEWS_RSS_URL,
    YAHOO_CHART_URL,
)

_LOGGER = logging.getLogger(__name__)

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumina Feeds sensors from a config entry."""
    session = async_get_clientsession(hass)
    options = entry.options
    entities: list[SensorEntity] = []

    news_interval = options.get(CONF_NEWS_INTERVAL, DEFAULT_NEWS_INTERVAL)
    stock_interval = options.get(CONF_STOCK_INTERVAL, DEFAULT_STOCK_INTERVAL)

    # ── News Interest Sensors ──
    for idx, interest in enumerate(options.get(CONF_INTERESTS, [])):
        name = interest.get("name", "News")
        keywords = interest.get("keywords", "")
        url = interest.get("url", "")
        language = interest.get("language", "en")
        max_items = interest.get("max_items", 15)

        if keywords or url:
            entities.append(
                LuminaNewsSensor(
                    session=session,
                    name=name,
                    keywords=keywords,
                    direct_url=url,
                    language=language,
                    max_items=max_items,
                    scan_interval=news_interval,
                    entry_id=entry.entry_id,
                    stagger_index=idx,
                )
            )

    # ── Stock Sensors ──
    symbols = options.get(CONF_STOCKS, [])
    if symbols:
        for symbol in symbols:
            entities.append(
                LuminaStockSensor(
                    session=session,
                    symbol=symbol.upper(),
                    scan_interval=stock_interval,
                    entry_id=entry.entry_id,
                )
            )
        # Summary sensor
        entities.append(
            LuminaStockSummarySensor(
                session=session,
                symbols=[s.upper() for s in symbols],
                scan_interval=stock_interval,
                entry_id=entry.entry_id,
            )
        )

    if entities:
        async_add_entities(entities, update_before_add=False)


# ═══════════════════════════════════════════════════════
# NEWS SENSOR
# ═══════════════════════════════════════════════════════


class LuminaNewsSensor(SensorEntity):
    """Sensor for news from RSS feeds (direct URL or Google News keywords)."""

    _attr_icon = "mdi:newspaper"
    _attr_should_poll = False

    def __init__(self, session, name, keywords, direct_url, language, max_items, scan_interval, entry_id, stagger_index=0):
        self._session = session
        self._feed_name = name
        self._keywords = keywords or ""
        self._direct_url = direct_url or ""
        self._language = language
        self._max_items = max_items
        self._scan_minutes = scan_interval
        self._stagger = stagger_index
        self._entries: list[dict[str, Any]] = []
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"Lumina Feed {name}"
        self._attr_unique_id = f"lumina_feed_{safe_name}_{entry_id[:8]}"

    @property
    def state(self) -> str:
        return f"{len(self._entries)} articles"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "entries": self._entries,
            "feed_name": self._feed_name,
            "keywords": self._keywords,
            "url": self._direct_url,
            "language": self._language,
        }

    async def async_added_to_hass(self) -> None:
        """Start periodic updates and trigger first fetch."""
        async_track_time_interval(
            self.hass, self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )
        self.hass.async_create_task(self._initial_fetch())

    async def _initial_fetch(self) -> None:
        """First fetch with stagger delay."""
        if self._stagger > 0:
            await asyncio.sleep(self._stagger * 3)
        await self.async_update()
        self.async_write_ha_state()

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch and parse the RSS feed."""
        try:
            # Build URL: direct RSS or Google News search
            if self._direct_url:
                url = self._direct_url
            else:
                parts = [k.strip() for k in self._keywords.split(",") if k.strip()]
                query = " OR ".join(parts)
                encoded_query = quote_plus(query)
                region = REGION_MAP.get(self._language, "US")
                url = GOOGLE_NEWS_RSS_URL.format(
                    query=encoded_query, lang=self._language, region=region,
                )

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s for %s", resp.status, self._feed_name)
                    return
                text = await resp.text()

            feed = await self.hass.async_add_executor_job(feedparser.parse, text)

            entries = []
            for entry in feed.entries[: self._max_items]:
                title = entry.get("title", "")
                source = ""

                # Google News format: "Title - Source Name"
                if not self._direct_url and " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1] if len(parts) > 1 else ""

                # Direct feeds: use feed title or author as source
                if self._direct_url and not source:
                    source = entry.get("author", "") or feed.feed.get("title", "") or ""

                # Extract clean summary (strip HTML tags)
                raw_summary = entry.get("summary", "") or entry.get("description", "")
                import re
                clean_summary = re.sub(r'<[^>]+>', '', raw_summary).strip()
                # Truncate to ~200 chars
                if len(clean_summary) > 200:
                    clean_summary = clean_summary[:197] + "..."

                entries.append({
                    "title": title,
                    "source": source,
                    "summary": clean_summary,
                    "published": entry.get("published", ""),
                    "link": entry.get("link", ""),
                })

            self._entries = entries

        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching %s", self._feed_name)
        except Exception as err:
            _LOGGER.error("Lumina Feeds: Error fetching %s: %s", self._feed_name, err)


# ═══════════════════════════════════════════════════════
# STOCK SENSOR
# ═══════════════════════════════════════════════════════


class LuminaStockSensor(SensorEntity):
    """Sensor for individual stock quote from Yahoo Finance."""

    _attr_icon = "mdi:chart-line"
    _attr_should_poll = False

    def __init__(self, session, symbol, scan_interval, entry_id):
        self._session = session
        self._symbol = symbol
        self._scan_minutes = scan_interval
        self._data: dict[str, Any] = {}
        safe_id = symbol.lower().replace("^", "idx_").replace("-", "_")
        self._attr_name = f"Lumina Stock {symbol}"
        self._attr_unique_id = f"lumina_stock_{safe_id}_{entry_id[:8]}"
        self._attr_unit_of_measurement = "USD"

    @property
    def state(self) -> float | str:
        return self._data.get("price", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._data

    async def async_added_to_hass(self) -> None:
        """Start periodic updates and trigger first fetch."""
        async_track_time_interval(
            self.hass, self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )
        self.hass.async_create_task(self._safe_update())

    async def _safe_update(self) -> None:
        """Safely update and write state."""
        await self.async_update()
        self.async_write_ha_state()

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch stock data using Yahoo Finance v8 chart API."""
        try:
            url = YAHOO_CHART_URL.format(symbol=self._symbol)
            async with self._session.get(
                url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s for stock %s (may be invalid symbol)", resp.status, self._symbol)
                    return
                data = await resp.json()

            chart = data.get("chart", {})
            result = chart.get("result", [])
            if not result:
                error = chart.get("error", {})
                _LOGGER.warning("Lumina Feeds: No data for %s: %s", self._symbol, error.get("description", "unknown"))
                return

            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
            currency = meta.get("currency", "USD")
            exchange = meta.get("exchangeName", "")
            name = meta.get("shortName", "") or meta.get("symbol", self._symbol)

            change = round(price - prev_close, 2) if prev_close else 0
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

            # Map currency to symbol
            currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "ILS": "₪", "JPY": "¥", "BTC": "₿"}
            currency_symbol = currency_symbols.get(currency, currency)

            self._attr_unit_of_measurement = currency
            self._data = {
                "symbol": self._symbol,
                "short_name": name,
                "price": round(price, 2),
                "regular_market_price": round(price, 2),
                "regular_market_previous_close": round(prev_close, 2),
                "regular_market_change": change,
                "regular_market_change_percent": change_pct,
                "currency": currency,
                "currency_symbol": currency_symbol,
                "market_state": meta.get("marketState", "CLOSED"),
                "trending": "up" if change >= 0 else "down",
                "exchange": exchange,
            }

        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching stock %s", self._symbol)
        except Exception as err:
            _LOGGER.error("Lumina Feeds: Error fetching stock %s: %s", self._symbol, err)


# ═══════════════════════════════════════════════════════
# STOCK SUMMARY SENSOR
# ═══════════════════════════════════════════════════════


class LuminaStockSummarySensor(SensorEntity):
    """Summary sensor with all stocks as attributes."""

    _attr_icon = "mdi:finance"
    _attr_name = "Lumina Stocks Summary"
    _attr_should_poll = False

    def __init__(self, session, symbols, scan_interval, entry_id):
        self._session = session
        self._symbols = symbols
        self._scan_minutes = scan_interval
        self._stocks: list[dict[str, Any]] = []
        self._attr_unique_id = f"lumina_stocks_summary_{entry_id[:8]}"

    @property
    def state(self) -> str:
        return f"{len(self._stocks)} stocks"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"stocks": self._stocks, "symbols": self._symbols}

    async def async_added_to_hass(self) -> None:
        async_track_time_interval(
            self.hass, self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )
        self.hass.async_create_task(self._safe_update())

    async def _safe_update(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch all stocks using individual v8 chart API calls."""
        currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "ILS": "₪", "JPY": "¥", "BTC": "₿"}
        stocks = []

        for symbol in self._symbols:
            try:
                url = YAHOO_CHART_URL.format(symbol=symbol)
                async with self._session.get(
                    url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("Lumina Feeds: HTTP %s for summary stock %s", resp.status, symbol)
                        continue
                    data = await resp.json()

                chart = data.get("chart", {})
                result = chart.get("result", [])
                if not result:
                    continue

                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice", 0)
                prev_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
                currency = meta.get("currency", "USD")
                name = meta.get("shortName", "") or meta.get("symbol", symbol)

                change = round(price - prev_close, 2) if prev_close else 0
                change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

                stocks.append({
                    "symbol": symbol,
                    "short_name": name,
                    "price": round(price, 2),
                    "change": change,
                    "change_percent": change_pct,
                    "currency": currency,
                    "currency_symbol": currency_symbols.get(currency, currency),
                    "trending": "up" if change >= 0 else "down",
                    "market_state": meta.get("marketState", "CLOSED"),
                })

            except asyncio.TimeoutError:
                _LOGGER.warning("Lumina Feeds: Timeout fetching summary stock %s", symbol)
            except Exception as err:
                _LOGGER.error("Lumina Feeds: Error fetching summary stock %s: %s", symbol, err)

        self._stocks = stocks
