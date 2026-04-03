"""Sensor platform for Lumina Feeds — news interests and stock quotes."""

import logging
import asyncio
from datetime import timedelta
from urllib.parse import quote_plus
from typing import Any

import aiohttp
import feedparser

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_INTERESTS,
    CONF_STOCKS,
    CONF_KEYWORDS,
    CONF_SYMBOLS,
    CONF_LANGUAGE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STOCK_SCAN_INTERVAL,
    DEFAULT_LANGUAGE,
    GOOGLE_NEWS_RSS_URL,
    YAHOO_QUOTE_URL,
)

_LOGGER = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Lumina Feeds sensor platform."""
    if discovery_info is None:
        return

    entities: list[SensorEntity] = []
    session = async_get_clientsession(hass)

    # ── News Interest Sensors ──
    interests = discovery_info.get(CONF_INTERESTS, [])
    news_interval = discovery_info.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    for interest in interests:
        name = interest.get("name", "News")
        keywords = interest.get(CONF_KEYWORDS, "")
        language = interest.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        max_items = interest.get("max_items", 15)

        sensor = LuminaNewsSensor(
            session=session,
            name=name,
            keywords=keywords,
            language=language,
            max_items=max_items,
            scan_interval=news_interval,
        )
        entities.append(sensor)

    # ── Stock Sensors ──
    stocks_config = discovery_info.get(CONF_STOCKS, {})
    if stocks_config:
        symbols = stocks_config.get(CONF_SYMBOLS, [])
        stock_interval = stocks_config.get(CONF_SCAN_INTERVAL, DEFAULT_STOCK_SCAN_INTERVAL)

        if symbols:
            # Individual stock sensors
            for symbol in symbols:
                sensor = LuminaStockSensor(
                    session=session,
                    symbol=symbol.upper(),
                    scan_interval=stock_interval,
                )
                entities.append(sensor)

            # Summary sensor (all stocks in one)
            summary = LuminaStockSummarySensor(
                session=session,
                symbols=[s.upper() for s in symbols],
                scan_interval=stock_interval,
            )
            entities.append(summary)

    if entities:
        async_add_entities(entities, update_before_add=True)


# ═══════════════════════════════════════════════════════
# NEWS SENSOR
# ═══════════════════════════════════════════════════════


class LuminaNewsSensor(SensorEntity):
    """Sensor for interest-based news from Google News RSS."""

    _attr_icon = "mdi:newspaper"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        name: str,
        keywords: str,
        language: str,
        max_items: int,
        scan_interval: int,
    ) -> None:
        """Initialize the news sensor."""
        self._session = session
        self._feed_name = name
        self._keywords = keywords
        self._language = language
        self._max_items = max_items
        self._scan_minutes = scan_interval
        self._entries: list[dict[str, Any]] = []
        self._attr_name = f"Lumina Feed {name}"
        self._attr_unique_id = f"lumina_feed_{name.lower().replace(' ', '_')}"

    @property
    def state(self) -> str:
        """Return number of articles."""
        return f"{len(self._entries)} articles"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return feed entries as attributes."""
        return {
            "entries": self._entries,
            "feed_name": self._feed_name,
            "keywords": self._keywords,
            "language": self._language,
        }

    async def async_added_to_hass(self) -> None:
        """Set up periodic updates."""
        async_track_time_interval(
            self.hass,
            self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )

    async def _async_update_handler(self, _now=None) -> None:
        """Handle scheduled update."""
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch and parse the Google News RSS feed."""
        try:
            # Build query: "keyword1 OR keyword2 OR keyword3"
            parts = [k.strip() for k in self._keywords.split(",") if k.strip()]
            query = " OR ".join(parts)
            encoded_query = quote_plus(query)

            # Map language to region
            region_map = {
                "en": "US", "he": "IL", "de": "DE", "fr": "FR",
                "es": "ES", "it": "IT", "pt": "BR", "ja": "JP",
                "ko": "KR", "zh": "CN", "ar": "SA", "ru": "RU",
                "nl": "NL", "sv": "SE", "da": "DK", "no": "NO",
            }
            region = region_map.get(self._language, "US")

            url = GOOGLE_NEWS_RSS_URL.format(
                query=encoded_query,
                lang=self._language,
                region=region,
            )

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s fetching %s", resp.status, self._feed_name)
                    return
                text = await resp.text()

            # Parse in executor to avoid blocking
            feed = await self.hass.async_add_executor_job(feedparser.parse, text)

            entries = []
            for entry in feed.entries[: self._max_items]:
                # Extract source from title (Google News format: "Title - Source")
                title = entry.get("title", "")
                source = ""
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1] if len(parts) > 1 else ""

                entries.append(
                    {
                        "title": title,
                        "source": source,
                        "published": entry.get("published", ""),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                    }
                )

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

    def __init__(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        scan_interval: int,
    ) -> None:
        """Initialize the stock sensor."""
        self._session = session
        self._symbol = symbol
        self._scan_minutes = scan_interval
        self._data: dict[str, Any] = {}
        safe_id = symbol.lower().replace("^", "idx_").replace("-", "_")
        self._attr_name = f"Lumina Stock {symbol}"
        self._attr_unique_id = f"lumina_stock_{safe_id}"
        self._attr_unit_of_measurement = "USD"

    @property
    def state(self) -> float | str:
        """Return current price."""
        return self._data.get("price", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return stock details."""
        return self._data

    async def async_added_to_hass(self) -> None:
        """Set up periodic updates."""
        async_track_time_interval(
            self.hass,
            self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )

    async def _async_update_handler(self, _now=None) -> None:
        """Handle scheduled update."""
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch stock quote from Yahoo Finance."""
        try:
            url = YAHOO_QUOTE_URL.format(symbols=self._symbol)
            async with self._session.get(
                url,
                headers=YAHOO_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s fetching stock %s", resp.status, self._symbol)
                    return
                data = await resp.json()

            results = data.get("quoteResponse", {}).get("result", [])
            if not results:
                return

            quote = results[0]
            price = quote.get("regularMarketPrice", 0)
            prev_close = quote.get("regularMarketPreviousClose", 0)
            change = quote.get("regularMarketChange", 0)
            change_pct = quote.get("regularMarketChangePercent", 0)
            currency = quote.get("currency", "USD")

            self._attr_unit_of_measurement = currency
            self._data = {
                "symbol": self._symbol,
                "short_name": quote.get("shortName", self._symbol),
                "long_name": quote.get("longName", ""),
                "price": round(price, 2),
                "regular_market_price": round(price, 2),
                "regular_market_previous_close": round(prev_close, 2),
                "regular_market_change": round(change, 2),
                "regular_market_change_percent": round(change_pct, 2),
                "currency": currency,
                "currency_symbol": quote.get("currencySymbol", "$"),
                "market_state": quote.get("marketState", "CLOSED"),
                "trending": "up" if change >= 0 else "down",
                "regular_market_volume": quote.get("regularMarketVolume", 0),
                "fifty_day_average": round(quote.get("fiftyDayAverage", 0), 2),
                "two_hundred_day_average": round(quote.get("twoHundredDayAverage", 0), 2),
                "market_cap": quote.get("marketCap", 0),
            }

        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching stock %s", self._symbol)
        except Exception as err:
            _LOGGER.error("Lumina Feeds: Error fetching stock %s: %s", self._symbol, err)


# ═══════════════════════════════════════════════════════
# STOCK SUMMARY SENSOR
# ═══════════════════════════════════════════════════════


class LuminaStockSummarySensor(SensorEntity):
    """Summary sensor with all stocks as attributes (for ticker display)."""

    _attr_icon = "mdi:finance"
    _attr_name = "Lumina Stocks Summary"
    _attr_unique_id = "lumina_stocks_summary"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        symbols: list[str],
        scan_interval: int,
    ) -> None:
        """Initialize the summary sensor."""
        self._session = session
        self._symbols = symbols
        self._scan_minutes = scan_interval
        self._stocks: list[dict[str, Any]] = []

    @property
    def state(self) -> str:
        """Return count of tracked stocks."""
        return f"{len(self._stocks)} stocks"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all stocks as entries for ticker rendering."""
        return {
            "stocks": self._stocks,
            "symbols": self._symbols,
        }

    async def async_added_to_hass(self) -> None:
        """Set up periodic updates."""
        async_track_time_interval(
            self.hass,
            self._async_update_handler,
            timedelta(minutes=self._scan_minutes),
        )

    async def _async_update_handler(self, _now=None) -> None:
        """Handle scheduled update."""
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch all stock quotes in a single API call."""
        try:
            symbols_str = ",".join(self._symbols)
            url = YAHOO_QUOTE_URL.format(symbols=symbols_str)

            async with self._session.get(
                url,
                headers=YAHOO_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Lumina Feeds: HTTP %s fetching stock summary", resp.status)
                    return
                data = await resp.json()

            results = data.get("quoteResponse", {}).get("result", [])
            stocks = []
            for quote in results:
                price = quote.get("regularMarketPrice", 0)
                change = quote.get("regularMarketChange", 0)
                change_pct = quote.get("regularMarketChangePercent", 0)
                stocks.append(
                    {
                        "symbol": quote.get("symbol", ""),
                        "short_name": quote.get("shortName", ""),
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_pct, 2),
                        "currency": quote.get("currency", "USD"),
                        "currency_symbol": quote.get("currencySymbol", "$"),
                        "trending": "up" if change >= 0 else "down",
                        "market_state": quote.get("marketState", "CLOSED"),
                    }
                )

            self._stocks = stocks

        except asyncio.TimeoutError:
            _LOGGER.warning("Lumina Feeds: Timeout fetching stock summary")
        except Exception as err:
            _LOGGER.error("Lumina Feeds: Error fetching stock summary: %s", err)
