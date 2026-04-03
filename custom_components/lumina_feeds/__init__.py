"""Lumina Feeds — Interest-based news and stock integration for Home Assistant."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Lumina Feeds from YAML configuration."""
    if DOMAIN not in config:
        return True

    hass.data[DOMAIN] = config[DOMAIN]

    # Forward setup to sensor platform
    hass.async_create_task(
        hass.helpers.discovery.async_load_platform("sensor", DOMAIN, config[DOMAIN], config)
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry (future use)."""
    return True
