"""Fenton Home Feedback: files the app's bug reports and feature requests on GitHub.

The GitHub token lives here, in the config entry, so the app never holds one: it uploads media and sends the
report over its Home Assistant sign-in (``views.py``), as FestivalNativeApps' app posts to its own service.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_REPOSITORY, DEFAULT_REPOSITORY, DOMAIN
from .github import Account, GitHubClient, GitHubError
from .views import register_views


@dataclass
class FeedbackRuntime:
    """The configured client and what its token reaches."""

    client: GitHubClient
    account: Account


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Verify the token and start accepting reports."""
    client = GitHubClient(async_get_clientsession(hass), entry.data[CONF_TOKEN],
                          entry.data.get(CONF_REPOSITORY, DEFAULT_REPOSITORY))
    try:
        account = await client.verify()
    except GitHubError as err:
        if err.code in ("token_rejected", "no_repository_access"):
            raise ConfigEntryAuthFailed(err.code) from err
        raise ConfigEntryNotReady(err.code) from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = FeedbackRuntime(client=client, account=account)
    register_views(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop using this entry (the views answer ``not_configured`` once no entry is loaded)."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
