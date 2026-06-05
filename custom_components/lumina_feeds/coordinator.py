"""DataUpdateCoordinators for Lumina Feeds.

Two coordinators, one per data source — they have different intervals (news
default 30 min, stocks default 15 min) and independent failure modes (Yahoo
being down shouldn't take news entities offline).

CoordinatorEntity subclasses (sensor.py) just read from .coordinator.data
instead of fetching themselves. Benefits:

  • one HTTP request per source per interval (was: one per sensor)
  • failures convert cleanly to UpdateFailed → entities go unavailable
  • options-reload doesn't trigger a fetch storm
  • integration tests can mock the client and skip the coordinator entirely
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import FeedClientError, NewsClient, YahooClient, interest_key

_LOGGER = logging.getLogger(__name__)


class NewsCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]] | None]]):
    """Polls every configured news interest once per interval.

    Data shape:  {interest_key: list[article_dict] | None}
                 None means that specific interest failed; entities show
                 unavailable. Other interests in the same dict are still
                 valid — one interest's outage doesn't take the rest down.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: NewsClient,
        interests: list[dict[str, Any]],
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="lumina_feeds_news",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self._client = client
        self._interests = interests

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]] | None]:
        results: dict[str, list[dict[str, Any]] | None] = {}
        for interest in self._interests:
            key = interest_key(interest)
            max_items = interest.get("max_items", 15)
            try:
                if interest.get("url"):
                    results[key] = await self._client.fetch_url(interest["url"], max_items)
                else:
                    results[key] = await self._client.fetch_keywords(
                        interest.get("keywords", ""),
                        interest.get("language", "en"),
                        max_items,
                    )
            except FeedClientError as err:
                _LOGGER.warning("Lumina Feeds: News fetch failed for %s: %s", key, err)
                results[key] = None
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Lumina Feeds: News fetch error for %s: %s", key, err)
                results[key] = None

        if not any(v is not None for v in results.values()) and results:
            # Every interest failed — surface as a coordinator-level failure.
            raise UpdateFailed("All news interests failed to fetch")

        return results


class StockCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any] | None]]):
    """Polls every configured stock symbol once per interval.

    Data shape:  {symbol: parsed_quote_dict | None}
                 None means that specific symbol failed (invalid ticker,
                 transient Yahoo error, etc.); other symbols still update.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: YahooClient,
        symbols: list[str],
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="lumina_feeds_stocks",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self._client = client
        self._symbols = symbols

    async def _async_update_data(self) -> dict[str, dict[str, Any] | None]:
        results = await self._client.fetch_quotes(self._symbols)
        if self._symbols and not any(v is not None for v in results.values()):
            raise UpdateFailed("All stock fetches failed")
        return results
