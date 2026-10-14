"""HTTP endpoints the app calls with its Home Assistant access token.

- ``GET /api/fenton_feedback/status``: ``{available, repository}``.
- ``POST /api/fenton_feedback/media?name=…&content_type=…`` with the raw file: ``{url}``. One file per request
  keeps each body under Home Assistant's request size limit.
- ``POST /api/fenton_feedback/report`` with the JSON report (``report.parse``): ``{number, url}``.

Errors answer ``{error, code}``; the app shows its own copy for each code, never the text.
"""

from __future__ import annotations

from collections import defaultdict, deque
from http import HTTPStatus
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import API_MEDIA, API_REPORT, API_STATUS, DOMAIN, MAX_MEDIA_BYTES, RATE_LIMIT, RATE_WINDOW_SECONDS
from .github import GitHubError
from .report import ReportError, compose, parse

if TYPE_CHECKING:
    from . import FeedbackRuntime

_REGISTERED = f"{DOMAIN}_views"
_RECENT: dict[str, deque[float]] = defaultdict(deque)


def register_views(hass: HomeAssistant) -> None:
    """Register the endpoints once per Home Assistant run."""
    if hass.data.get(_REGISTERED):
        return
    for view in (StatusView(), MediaView(), ReportView()):
        hass.http.register_view(view)
    hass.data[_REGISTERED] = True


def _error(code: str, status: HTTPStatus) -> web.Response:
    return web.json_response({"error": code, "code": code}, status=status)


def _runtime(request: web.Request) -> FeedbackRuntime | None:
    return request.app[KEY_HASS].data.get(DOMAIN)


def _github_error(err: GitHubError) -> web.Response:
    if err.code == "rate_limited":
        return _error(err.code, HTTPStatus.TOO_MANY_REQUESTS)
    if err.code == "attachment_rejected":
        return _error(err.code, HTTPStatus.UNPROCESSABLE_ENTITY)
    # The owner's token or GitHub itself: nothing the person can fix in the app.
    return _error(f"github_{err.code}" if not err.code.startswith("github_") else err.code, HTTPStatus.BAD_GATEWAY)


def _rate_limited(user_id: str, now: float | None = None) -> bool:
    """Whether this user has sent ``RATE_LIMIT`` reports in the last window (and record this one if not)."""
    now = time.monotonic() if now is None else now
    recent = _RECENT[user_id]
    while recent and now - recent[0] > RATE_WINDOW_SECONDS:
        recent.popleft()
    if len(recent) >= RATE_LIMIT:
        return True
    recent.append(now)
    return False


class StatusView(HomeAssistantView):
    """Whether reports can be filed."""

    url = API_STATUS
    name = "api:fenton_feedback:status"

    async def get(self, request: web.Request) -> web.Response:
        runtime = _runtime(request)
        return self.json({"available": runtime is not None,
                          "repository": runtime.client.repository if runtime else None})


class MediaView(HomeAssistantView):
    """Uploads one attachment to GitHub."""

    url = API_MEDIA
    name = "api:fenton_feedback:media"

    async def post(self, request: web.Request) -> web.Response:
        runtime = _runtime(request)
        if runtime is None:
            return _error("not_configured", HTTPStatus.SERVICE_UNAVAILABLE)
        content_type = request.query.get("content_type", "")
        name = request.query.get("name", "attachment")[:120] or "attachment"
        if not content_type.startswith(("image/", "video/")):
            return _error("unsupported_media", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if (request.content_length or 0) > MAX_MEDIA_BYTES:
            return _error("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        data = await request.read()
        if not data:
            return _error("invalid_form", HTTPStatus.BAD_REQUEST)
        if len(data) > MAX_MEDIA_BYTES:
            return _error("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            url = await runtime.client.upload(runtime.account.repository_id, name, content_type, data)
        except GitHubError as err:
            return _github_error(err)
        return self.json({"url": url})


class ReportView(HomeAssistantView):
    """Files the issue, naming the signed-in Home Assistant user."""

    url = API_REPORT
    name = "api:fenton_feedback:report"

    async def post(self, request: web.Request) -> web.Response:
        runtime = _runtime(request)
        if runtime is None:
            return _error("not_configured", HTTPStatus.SERVICE_UNAVAILABLE)
        user = request.get("hass_user")
        if _rate_limited(user.id if user else "anonymous"):
            return _error("rate_limited", HTTPStatus.TOO_MANY_REQUESTS)
        try:
            payload: Any = await request.json()
            report = parse(payload)
        except ReportError as err:
            return _error(err.code, HTTPStatus.BAD_REQUEST)
        except ValueError:
            return _error("invalid_form", HTTPStatus.BAD_REQUEST)
        title, body, labels = compose(report, user.name if user else None)
        try:
            number, url = await runtime.client.create_issue(title, body, labels)
        except GitHubError as err:
            return _github_error(err)
        return self.json({"number": number, "url": url}, status_code=HTTPStatus.CREATED)
