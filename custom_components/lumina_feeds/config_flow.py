"""Config flow for Lumina Feeds integration."""

import logging
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import YahooClient
from .const import (
    DOMAIN,
    CONF_INTERESTS,
    CONF_STOCKS,
    CONF_NEWS_INTERVAL,
    CONF_STOCK_INTERVAL,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_STOCK_INTERVAL,
    MAX_INTERESTS,
    MAX_SYMBOLS,
    MAX_LINE_LENGTH,
    SYMBOL_PATTERN,
)
from .url_safety import is_safe_url

_SYMBOL_RE = re.compile(SYMBOL_PATTERN)

_LOGGER = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


class LuminaFeedsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lumina Feeds."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Lumina Feeds",
                data={},
                options={
                    CONF_INTERESTS: [],
                    CONF_STOCKS: [],
                    CONF_NEWS_INTERVAL: DEFAULT_NEWS_INTERVAL,
                    CONF_STOCK_INTERVAL: DEFAULT_STOCK_INTERVAL,
                },
            )

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow handler."""
        return LuminaFeedsOptionsFlow(config_entry)


class LuminaFeedsOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Lumina Feeds."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry
        self._search_results: list[dict] = []

    async def async_step_init(self, user_input=None):
        """Main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["interests", "stocks", "stock_search", "intervals"],
        )

    # ─── Interests ───────────────────────────────────

    async def async_step_interests(self, user_input=None):
        """Manage news interests."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input.get("interests_text", "")
            interests, errors = self._parse_interests(raw)
            if not errors:
                options = dict(self._config_entry.options)
                options[CONF_INTERESTS] = interests
                return self.async_create_entry(title="", data=options)

        current = self._config_entry.options.get(CONF_INTERESTS, [])
        lines = []
        for i in current:
            if i.get("url"):
                lines.append(f"{i['name']} | {i['url']}")
            else:
                lines.append(f"{i['name']} | {i.get('keywords', '')} | {i.get('language', 'en')}")
        # On error, echo the user's submission back so they can edit it.
        suggested = user_input.get("interests_text", "") if user_input else "\n".join(lines)

        return self.async_show_form(
            step_id="interests",
            data_schema=vol.Schema({
                vol.Required("interests_text", description={"suggested_value": suggested}): TextSelector(TextSelectorConfig(multiline=True)),
            }),
            errors=errors,
        )

    def _parse_interests(self, raw: str) -> tuple[list[dict], dict[str, str]]:
        """Parse + validate the multiline interests blob."""
        interests: list[dict] = []
        errors: dict[str, str] = {}

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if len(line) > MAX_LINE_LENGTH:
                errors["base"] = "line_too_long"
                return [], errors
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            source = parts[1]
            interest = {"name": parts[0], "max_items": 15}
            if source.startswith(("http://", "https://")):
                ok, reason = is_safe_url(source)
                if not ok:
                    errors["base"] = "unsafe_url" if reason in ("private_ip", "private_host") else "invalid_url"
                    return [], errors
                interest["url"] = source
            else:
                interest["keywords"] = source
                interest["language"] = parts[2] if len(parts) > 2 else "en"
            interests.append(interest)

        if len(interests) > MAX_INTERESTS:
            errors["base"] = "too_many_interests"
            return [], errors

        return interests, errors

    # ─── Stocks: Edit ────────────────────────────────

    async def async_step_stocks(self, user_input=None):
        """Edit stock symbols manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input.get("symbols_text", "")
            if len(raw) > MAX_LINE_LENGTH * 4:
                errors["base"] = "line_too_long"
            else:
                symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
                invalid = [s for s in symbols if not _SYMBOL_RE.match(s)]
                if invalid:
                    errors["base"] = "invalid_symbol"
                elif len(symbols) > MAX_SYMBOLS:
                    errors["base"] = "too_many_symbols"
                else:
                    options = dict(self._config_entry.options)
                    options[CONF_STOCKS] = symbols
                    return self.async_create_entry(title="", data=options)

        current = self._config_entry.options.get(CONF_STOCKS, [])
        suggested = user_input.get("symbols_text", "") if user_input else ", ".join(current)

        return self.async_show_form(
            step_id="stocks",
            data_schema=vol.Schema({
                vol.Required("symbols_text", description={"suggested_value": suggested}): str,
            }),
            errors=errors,
        )

    # ─── Stocks: Search ──────────────────────────────

    async def async_step_stock_search(self, user_input=None):
        """Search for stocks by company name."""
        errors = {}

        if user_input is not None:
            query = user_input.get("search_query", "").strip()
            if query:
                results = await self._search_yahoo(query)
                if results:
                    self._search_results = results
                    return await self.async_step_stock_results()
                else:
                    errors["base"] = "no_results"

        return self.async_show_form(
            step_id="stock_search",
            data_schema=vol.Schema({
                vol.Required("search_query"): str,
            }),
            errors=errors,
        )

    async def async_step_stock_results(self, user_input=None):
        """Show search results and let user pick."""
        if user_input is not None:
            selected = user_input.get("selected_symbols", [])
            if isinstance(selected, str):
                selected = [selected]
            if selected:
                options = dict(self._config_entry.options)
                current = list(options.get(CONF_STOCKS, []))
                for sym in selected:
                    if sym.upper() not in [s.upper() for s in current]:
                        current.append(sym.upper())
                options[CONF_STOCKS] = current
                return self.async_create_entry(title="", data=options)

            return await self.async_step_stock_search()

        if not self._search_results:
            return await self.async_step_stock_search()

        # Build options for multi-select using HA's SelectSelector
        select_options = [
            {
                "label": f"{r['symbol']} — {r['name']} ({r['exchange']})",
                "value": r["symbol"],
            }
            for r in self._search_results
        ]

        return self.async_show_form(
            step_id="stock_results",
            data_schema=vol.Schema({
                vol.Required("selected_symbols"): SelectSelector(
                    SelectSelectorConfig(
                        options=select_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def _search_yahoo(self, query: str) -> list[dict]:
        """Search Yahoo Finance for stock symbols. Delegates to YahooClient."""
        session = async_get_clientsession(self.hass)
        return await YahooClient(session).search(query)

    # ─── Intervals ───────────────────────────────────

    async def async_step_intervals(self, user_input=None):
        """Configure scan intervals."""
        if user_input is not None:
            options = dict(self._config_entry.options)
            options[CONF_NEWS_INTERVAL] = user_input.get(CONF_NEWS_INTERVAL, DEFAULT_NEWS_INTERVAL)
            options[CONF_STOCK_INTERVAL] = user_input.get(CONF_STOCK_INTERVAL, DEFAULT_STOCK_INTERVAL)
            return self.async_create_entry(title="", data=options)

        news_int = self._config_entry.options.get(CONF_NEWS_INTERVAL, DEFAULT_NEWS_INTERVAL)
        stock_int = self._config_entry.options.get(CONF_STOCK_INTERVAL, DEFAULT_STOCK_INTERVAL)

        return self.async_show_form(
            step_id="intervals",
            data_schema=vol.Schema({
                vol.Optional(CONF_NEWS_INTERVAL, default=news_int): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=1440)
                ),
                vol.Optional(CONF_STOCK_INTERVAL, default=stock_int): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=1440)
                ),
            }),
        )
