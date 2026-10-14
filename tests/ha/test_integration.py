"""Config flow and the HTTP endpoints inside a real Home Assistant, with GitHub patched out."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fenton_feedback import views
from custom_components.fenton_feedback.const import CONF_REPOSITORY, DOMAIN
from custom_components.fenton_feedback.github import Account, GitHubError

CLIENT = "custom_components.fenton_feedback.github.GitHubClient"
URL = "https://github.com/user-attachments/assets/abc-1"


async def test_flow_creates_the_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(f"{CLIENT}.verify", AsyncMock(side_effect=GitHubError("token_rejected", 401))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: "bad", CONF_REPOSITORY: "SFenton/fenton-hass-requests"})
    assert result["errors"] == {"base": "token_rejected"}
    with patch(f"{CLIENT}.verify", AsyncMock(return_value=Account("SFenton", 42))), \
         patch("custom_components.fenton_feedback.async_setup_entry", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: " good ", CONF_REPOSITORY: "SFenton/fenton-hass-requests"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SFenton/fenton-hass-requests (@SFenton)"
    assert result["data"] == {CONF_TOKEN: "good", CONF_REPOSITORY: "SFenton/fenton-hass-requests"}


@pytest.fixture
async def configured(hass: HomeAssistant):
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOKEN: "t", CONF_REPOSITORY: "SFenton/fenton-hass-requests"},
                            unique_id="sfenton/fenton-hass-requests")
    entry.add_to_hass(hass)
    with patch(f"{CLIENT}.verify", AsyncMock(return_value=Account("SFenton", 42))):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    views._RECENT.clear()
    return entry


async def test_endpoints(hass: HomeAssistant, configured, hass_client) -> None:
    client = await hass_client()
    status = await client.get("/api/fenton_feedback/status")
    assert await status.json() == {"available": True, "repository": "SFenton/fenton-hass-requests"}

    with patch(f"{CLIENT}.upload", AsyncMock(return_value=URL)) as upload:
        media = await client.post("/api/fenton_feedback/media?name=shot.png&content_type=image/png", data=b"png")
    assert (await media.json()) == {"url": URL}
    upload.assert_awaited_once_with(42, "shot.png", "image/png", b"png")
    refused = await client.post("/api/fenton_feedback/media?name=a.txt&content_type=text/plain", data=b"x")
    assert refused.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    report = {"kind": "bug", "platform": "ios", "title": "[Bug] Lights", "description": "Flicker",
              "diagnostics": [["App", "1 (1)"]], "media": [{"name": "shot.png", "url": URL}]}
    with patch(f"{CLIENT}.create_issue", AsyncMock(return_value=(7, "https://github.com/x/7"))) as create:
        filed = await client.post("/api/fenton_feedback/report", json=report)
    assert filed.status == HTTPStatus.CREATED
    assert await filed.json() == {"number": 7, "url": "https://github.com/x/7"}
    title, body, labels = create.await_args.args
    assert title == "[Bug] Lights" and labels == ["Bug", "From App", "iOS"]
    assert f"![shot.png]({URL})" in body and "| Reported by |" in body

    bad = await client.post("/api/fenton_feedback/report", json={"kind": "bug"})
    assert bad.status == HTTPStatus.BAD_REQUEST and (await bad.json())["code"] == "invalid_form"
    with patch(f"{CLIENT}.create_issue", AsyncMock(side_effect=GitHubError("token_rejected", 401))):
        failed = await client.post("/api/fenton_feedback/report", json=report)
    assert failed.status == HTTPStatus.BAD_GATEWAY and (await failed.json())["code"] == "github_token_rejected"


async def test_rate_limit_and_unload(hass: HomeAssistant, configured, hass_client) -> None:
    client = await hass_client()
    report = {"kind": "feature", "platform": "ipados", "title": "[Feature] X", "description": "Y"}
    with patch(f"{CLIENT}.create_issue", AsyncMock(return_value=(1, "https://github.com/x/1"))):
        codes = [(await client.post("/api/fenton_feedback/report", json=report)).status for _ in range(11)]
    assert codes[:10] == [HTTPStatus.CREATED] * 10 and codes[10] == HTTPStatus.TOO_MANY_REQUESTS
    assert await hass.config_entries.async_unload(configured.entry_id)
    status = await client.get("/api/fenton_feedback/status")
    assert (await status.json())["available"] is False
    missing = await client.post("/api/fenton_feedback/report", json=report)
    assert missing.status == HTTPStatus.SERVICE_UNAVAILABLE


async def test_requires_auth(hass: HomeAssistant, configured, hass_client_no_auth) -> None:
    client = await hass_client_no_auth()
    assert (await client.get("/api/fenton_feedback/status")).status == HTTPStatus.UNAUTHORIZED
    with patch(f"{CLIENT}.upload", AsyncMock(return_value=URL)) as upload, \
         patch(f"{CLIENT}.create_issue", AsyncMock(return_value=(1, "https://github.com/x/1"))) as create:
        media = await client.post("/api/fenton_feedback/media?name=a.png&content_type=image/png", data=b"png")
        report = await client.post("/api/fenton_feedback/report", json={"kind": "feature", "platform": "ios",
                                                                         "title": "[Feature] X", "description": "Y"})
    assert media.status == HTTPStatus.UNAUTHORIZED and report.status == HTTPStatus.UNAUTHORIZED
    upload.assert_not_awaited()
    create.assert_not_awaited()


async def test_media_is_rate_limited(hass: HomeAssistant, configured, hass_client) -> None:
    client = await hass_client()
    with patch(f"{CLIENT}.upload", AsyncMock(return_value=URL)):
        codes = [(await client.post("/api/fenton_feedback/media?name=a.png&content_type=image/png", data=b"png")).status
                 for _ in range(41)]
    assert codes[:40] == [HTTPStatus.OK] * 40 and codes[40] == HTTPStatus.TOO_MANY_REQUESTS


async def test_refused_media_does_not_count_and_stale_users_are_forgotten(hass: HomeAssistant, configured, hass_client) -> None:
    client = await hass_client()
    for _ in range(45):
        refused = await client.post("/api/fenton_feedback/media?name=a.txt&content_type=text/plain", data=b"x")
        assert refused.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    with patch(f"{CLIENT}.upload", AsyncMock(return_value=URL)):
        ok = await client.post("/api/fenton_feedback/media?name=a.png&content_type=image/png", data=b"png")
    assert ok.status == HTTPStatus.OK
    views._RECENT["media:someone-else"].append(-10_000.0)
    assert views._rate_limited("media:fresh", now=0.0, limit=40) is False
    assert "media:someone-else" not in views._RECENT


async def test_unloading_one_entry_keeps_the_other(hass: HomeAssistant, configured, hass_client) -> None:
    second = MockConfigEntry(domain=DOMAIN, data={CONF_TOKEN: "t2", CONF_REPOSITORY: "SFenton/other"}, unique_id="sfenton/other")
    second.add_to_hass(hass)
    with patch(f"{CLIENT}.verify", AsyncMock(return_value=Account("SFenton", 43))):
        assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(second.entry_id)
    client = await hass_client()
    assert (await (await client.get("/api/fenton_feedback/status")).json())["available"] is True


async def test_setup_failures_ask_for_a_new_token(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOKEN: "t", CONF_REPOSITORY: "o/r"})
    entry.add_to_hass(hass)
    with patch(f"{CLIENT}.verify", AsyncMock(side_effect=GitHubError("token_rejected", 401))):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())
