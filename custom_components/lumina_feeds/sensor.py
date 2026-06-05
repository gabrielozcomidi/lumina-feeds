"""Lumina Feeds sensor entities.

After the Phase 4 refactor these are thin CoordinatorEntity subclasses —
all HTTP/parsing lives in client.py and all scheduling in coordinator.py.
Each entity just renders whatever the coordinator put in its data dict
for the entity's key.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import NewsClient, YahooClient, interest_key
from .const import (
    CONF_INTERESTS,
    CONF_NEWS_INTERVAL,
    CONF_STOCK_INTERVAL,
    CONF_STOCKS,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_STOCK_INTERVAL,
    DOMAIN,
)
from .coordinator import NewsCoordinator, StockCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumina Feeds sensors from a config entry."""
    session = async_get_clientsession(hass)
    options = entry.options

    interests: list[dict[str, Any]] = options.get(CONF_INTERESTS, [])
    symbols: list[str] = [s.upper() for s in options.get(CONF_STOCKS, [])]

    entities: list[SensorEntity] = []
    expected_unique_ids: set[str] = set()

    # Store coordinators in hass.data so options-reload can replace them
    # cleanly. Each entity holds a reference to its coordinator.
    entry_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})

    if interests:
        news_client = NewsClient(hass, session)
        news_coord = NewsCoordinator(
            hass,
            news_client,
            interests,
            options.get(CONF_NEWS_INTERVAL, DEFAULT_NEWS_INTERVAL),
        )
        await news_coord.async_config_entry_first_refresh()
        entry_data["news_coordinator"] = news_coord
        for interest in interests:
            if interest.get("keywords") or interest.get("url"):
                entities.append(LuminaNewsSensor(news_coord, interest, entry.entry_id))

    if symbols:
        yahoo_client = YahooClient(session)
        stock_coord = StockCoordinator(
            hass,
            yahoo_client,
            symbols,
            options.get(CONF_STOCK_INTERVAL, DEFAULT_STOCK_INTERVAL),
        )
        await stock_coord.async_config_entry_first_refresh()
        entry_data["stock_coordinator"] = stock_coord
        for symbol in symbols:
            entities.append(LuminaStockSensor(stock_coord, symbol, entry.entry_id))
        entities.append(LuminaStockSummarySensor(stock_coord, symbols, entry.entry_id))

    for e in entities:
        if e.unique_id:
            expected_unique_ids.add(e.unique_id)

    # Clean up entities left over from removed interests/symbols.
    try:
        ent_reg = er.async_get(hass)
        for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if ent_entry.unique_id not in expected_unique_ids:
                _LOGGER.info("Lumina Feeds: Removing stale entity %s", ent_entry.entity_id)
                ent_reg.async_remove(ent_entry.entity_id)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Lumina Feeds: Entity cleanup skipped: %s", err)

    if entities:
        async_add_entities(entities)


# ──────────────────────────────────────────────────────────────────────
# News
# ──────────────────────────────────────────────────────────────────────


class LuminaNewsSensor(CoordinatorEntity[NewsCoordinator], SensorEntity):
    """News interest sensor — count of articles in state, articles in attrs."""

    _attr_icon = "mdi:newspaper"
    _attr_native_unit_of_measurement = "articles"
    # entries[] can be ~5 KB per update — keep it out of the recorder DB.
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(
        self,
        coordinator: NewsCoordinator,
        interest: dict[str, Any],
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._interest = interest
        self._key = interest_key(interest)
        name = interest.get("name", "News")
        safe = name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"Lumina Feed {name}"
        self._attr_unique_id = f"lumina_feed_{safe}_{entry_id[:8]}"

    @property
    def _entries(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        return data.get(self._key) or []

    @property
    def native_value(self) -> int:
        return len(self._entries)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "entries": self._entries,
            "feed_name": self._interest.get("name", ""),
            "keywords": self._interest.get("keywords", ""),
            "url": self._interest.get("url", ""),
            "language": self._interest.get("language", "en"),
        }

    @property
    def available(self) -> bool:
        # Coordinator's own availability + our key's data exists (not None).
        if not super().available:
            return False
        data = self.coordinator.data or {}
        return data.get(self._key) is not None


# ──────────────────────────────────────────────────────────────────────
# Stocks — individual
# ──────────────────────────────────────────────────────────────────────


class LuminaStockSensor(CoordinatorEntity[StockCoordinator], SensorEntity):
    """Single-symbol stock price sensor."""

    _attr_icon = "mdi:chart-line"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator: StockCoordinator,
        symbol: str,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        safe = symbol.lower().replace("^", "idx_").replace("-", "_")
        self._attr_name = f"Lumina Stock {symbol}"
        self._attr_unique_id = f"lumina_stock_{safe}_{entry_id[:8]}"
        self._attr_native_unit_of_measurement = "USD"  # refined below from data

    @property
    def _data(self) -> dict[str, Any]:
        return ((self.coordinator.data or {}).get(self._symbol)) or {}

    @property
    def native_value(self) -> float | None:
        price = self._data.get("price")
        return float(price) if isinstance(price, (int, float)) else None

    @property
    def native_unit_of_measurement(self) -> str:
        return self._data.get("currency") or "USD"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._data

    @property
    def available(self) -> bool:
        return super().available and bool(self._data)


# ──────────────────────────────────────────────────────────────────────
# Stocks — summary
# ──────────────────────────────────────────────────────────────────────


class LuminaStockSummarySensor(CoordinatorEntity[StockCoordinator], SensorEntity):
    """Aggregate sensor — count in state, all quotes in attributes."""

    _attr_icon = "mdi:finance"
    _attr_name = "Lumina Stocks Summary"
    _attr_native_unit_of_measurement = "stocks"
    _unrecorded_attributes = frozenset({"stocks"})

    def __init__(
        self,
        coordinator: StockCoordinator,
        symbols: list[str],
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._symbols = symbols
        self._attr_unique_id = f"lumina_stocks_summary_{entry_id[:8]}"

    @property
    def _stocks(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        return [data[s] for s in self._symbols if data.get(s)]

    @property
    def native_value(self) -> int:
        return len(self._stocks)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"stocks": self._stocks, "symbols": self._symbols}
