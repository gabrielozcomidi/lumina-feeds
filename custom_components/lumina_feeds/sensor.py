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
    YAHOO_QUOTE_URL,
)

_LOGGER = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
    for interest in options.get(CONF_INTERESTS, []):
        name = interest.get("name", "News")
        keywords = interest.get("keywords", "")
        language = interest.get("language", "en")
        max_items = interest.get("max_items", 15)

        if keywords:
            entities.append(
                LuminaNewsSensor(
                    session=session,
                    name=name,
                    keywords=keywords,
                    language=language,
                    max_items=max_items,
                    scan_interval=news_interval,
                    entry_id=entry.entry_id,
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
        async_add_entities(entities, update_before_add=True)


# ═══════════════════════════════════════════════════════
# NEWS SENSOR
# ═══════════════════════════════════════════════════════


class LuminaNewsSensor(SensorEntity):
    """Sensor for interest-based news from Google News RSS."""

    _attr_icon = "mdi:newspaper"
    _attr_has_entity_name = True

    def __init__(self, session, name, keywords, language, max_items, scan_interval, entry_id):
        self._session = session
        self._feed_name = name
        self._keywords = keywords
        self._language = language
        self._max_items = max_items
        self._scan_minutes = scan_interval
        self._entries: list[dict[str, Any]] = []
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"Feed {name}"
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
            "language": self._language,
        }

    async def async_added_to_hass(self) -> None:
        async_track_time_interval(
            self.hass, self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        try:
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
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1] if len(parts) > 1 else ""

                entries.append({
                    "title": title,
                    "source": source,
                    "published": entry.get("published", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
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
    _attr_has_entity_name = True

    def __init__(self, session, symbol, scan_interval, entry_id):
        self._session = session
        self._symbol = symbol
        self._scan_minutes = scan_interval
        self._data: dict[str, Any] = {}
        safe_id = symbol.lower().replace("^", "idx_").replace("-", "_")
        self._attr_name = f"Stock {symbol}"
        self._attr_unique_id = f"lumina_stock_{safe_id}_{entry_id[:8]}"
        self._attr_unit_of_measurement = "USD"

    @property
    def state(self) -> float | str:
        return self._data.get("price", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._data

    async def async_added_to_hass(self) -> None:
        async_track_time_interval(
            self.hass, self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        try:
            url = YAHOO_QUOTE_URL.format(symbols=self._symbol)
            async with self._session.get(
                url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s for stock %s", resp.status, self._symbol)
                    return
                data = await resp.json()

            results = data.get("quoteResponse", {}).get("result", [])
            if not results:
                return

            q = results[0]
            price = q.get("regularMarketPrice", 0)
            change = q.get("regularMarketChange", 0)
            change_pct = q.get("regularMarketChangePercent", 0)

            self._attr_unit_of_measurement = q.get("currency", "USD")
            self._data = {
                "symbol": self._symbol,
                "short_name": q.get("shortName", self._symbol),
                "long_name": q.get("longName", ""),
                "price": round(price, 2),
                "regular_market_price": round(price, 2),
                "regular_market_previous_close": round(q.get("regularMarketPreviousClose", 0), 2),
                "regular_market_change": round(change, 2),
                "regular_market_change_percent": round(change_pct, 2),
                "currency": q.get("currency", "USD"),
                "currency_symbol": q.get("currencySymbol", "$"),
                "market_state": q.get("marketState", "CLOSED"),
                "trending": "up" if change >= 0 else "down",
                "regular_market_volume": q.get("regularMarketVolume", 0),
                "fifty_day_average": round(q.get("fiftyDayAverage", 0), 2),
                "two_hundred_day_average": round(q.get("twoHundredDayAverage", 0), 2),
                "market_cap": q.get("marketCap", 0),
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
    _attr_has_entity_name = True
    _attr_name = "Stocks Summary"

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

    async def _async_update_handler(self, _now=None) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        try:
            symbols_str = ",".join(self._symbols)
            url = YAHOO_QUOTE_URL.format(symbols=symbols_str)

            async with self._session.get(
                url, headers=YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()

            results = data.get("quoteResponse", {}).get("result", [])
            stocks = []
            for q in results:
                price = q.get("regularMarketPrice", 0)
                change = q.get("regularMarketChange", 0)
                change_pct = q.get("regularMarketChangePercent", 0)
                stocks.append({
                    "symbol": q.get("symbol", ""),
                    "short_name": q.get("shortName", ""),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "currency": q.get("currency", "USD"),
                    "currency_symbol": q.get("currencySymbol", "$"),
                    "trending": "up" if change >= 0 else "down",
                    "market_state": q.get("marketState", "CLOSED"),
                })
            self._stocks = stocks

        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching stock summary")
        except Exception as err:
            _LOGGER.error("Lumina Feeds: Error fetching stock summary: %s", err)
