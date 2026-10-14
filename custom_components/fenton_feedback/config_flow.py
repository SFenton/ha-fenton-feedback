"""Config flow: paste a fine-grained GitHub token, checked before it is saved."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_REPOSITORY, DEFAULT_REPOSITORY, DOMAIN
from .github import GitHubClient, GitHubError

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class FentonFeedbackConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the relay with the owner's GitHub token."""

    VERSION = 1

    async def _verify(self, token: str, repository: str) -> tuple[str | None, str | None]:
        """Return (login, error code)."""
        client = GitHubClient(async_get_clientsession(self.hass), token, repository)
        try:
            account = await client.verify()
        except GitHubError as err:
            return None, err.code if err.code in ("token_rejected", "no_repository_access", "rate_limited") else "cannot_connect"
        return account.login, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the token and the request repository."""
        errors: dict[str, str] = {}
        if user_input is not None:
            repository = user_input[CONF_REPOSITORY].strip()
            await self.async_set_unique_id(repository.lower())
            self._abort_if_unique_id_configured()
            login, error = await self._verify(user_input[CONF_TOKEN], repository)
            if error is None:
                return self.async_create_entry(
                    title=f"{repository} (@{login})",
                    data={CONF_TOKEN: user_input[CONF_TOKEN].strip(), CONF_REPOSITORY: repository},
                )
            errors["base"] = error
        schema = vol.Schema({
            vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
            vol.Required(CONF_REPOSITORY, default=DEFAULT_REPOSITORY): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The saved token stopped working (expired or revoked)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a replacement token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _, error = await self._verify(user_input[CONF_TOKEN], entry.data[CONF_REPOSITORY])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN].strip()})
            errors["base"] = error
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR}),
                                    errors=errors, description_placeholders={"repository": entry.data[CONF_REPOSITORY]})
