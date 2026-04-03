"""Config flow for Lumina Feeds integration."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_INTERESTS,
    CONF_STOCKS,
    CONF_NEWS_INTERVAL,
    CONF_STOCK_INTERVAL,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_STOCK_INTERVAL,
)


class LuminaFeedsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lumina Feeds."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step — just confirm setup."""
        if user_input is not None:
            # Check if already configured
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

        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "description": "Set up Lumina Feeds to get personalized news and stock data. You'll configure your interests and stocks in the next step."
            },
        )

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

    async def async_step_init(self, user_input=None):
        """Main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["interests", "stocks", "intervals"],
        )

    # ─── Interests ───────────────────────────────────

    async def async_step_interests(self, user_input=None):
        """Manage news interests."""
        if user_input is not None:
            # Parse the text areas into structured data
            interests = []
            raw = user_input.get("interests_text", "")
            for line in raw.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Format: "Name | keywords | language"
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    interest = {
                        "name": parts[0],
                        "keywords": parts[1],
                        "language": parts[2] if len(parts) > 2 else "en",
                        "max_items": 15,
                    }
                    interests.append(interest)

            options = dict(self._config_entry.options)
            options[CONF_INTERESTS] = interests
            return self.async_create_entry(title="", data=options)

        # Build current interests text
        current = self._config_entry.options.get(CONF_INTERESTS, [])
        lines = []
        for i in current:
            lang = i.get("language", "en")
            lines.append(f"{i['name']} | {i['keywords']} | {lang}")

        current_text = "\n".join(lines) if lines else ""

        return self.async_show_form(
            step_id="interests",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "interests_text",
                        default=current_text,
                        description={"suggested_value": current_text},
                    ): str,
                }
            ),
            description_placeholders={
                "format_hint": "One interest per line: Name | keywords | language\nExample: Smart Home | home assistant, IoT | en"
            },
        )

    # ─── Stocks ──────────────────────────────────────

    async def async_step_stocks(self, user_input=None):
        """Manage stock symbols."""
        if user_input is not None:
            raw = user_input.get("symbols_text", "")
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]

            options = dict(self._config_entry.options)
            options[CONF_STOCKS] = symbols
            return self.async_create_entry(title="", data=options)

        current = self._config_entry.options.get(CONF_STOCKS, [])
        current_text = ", ".join(current) if current else ""

        return self.async_show_form(
            step_id="stocks",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "symbols_text",
                        default=current_text,
                        description={"suggested_value": current_text},
                    ): str,
                }
            ),
            description_placeholders={
                "format_hint": "Comma-separated symbols: AAPL, MSFT, GOOGL, BTC-USD, ^GSPC"
            },
        )

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
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NEWS_INTERVAL, default=news_int): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=1440)
                    ),
                    vol.Optional(CONF_STOCK_INTERVAL, default=stock_int): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=1440)
                    ),
                }
            ),
        )
