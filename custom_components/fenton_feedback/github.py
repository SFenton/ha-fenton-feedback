"""GitHub calls for the relay (aiohttp only, no Home Assistant imports, so tests run anywhere).

Endpoints: ``GET /user`` and ``GET /repos/{repo}`` to verify the token, ``POST
uploads.github.com/user-attachments/assets`` for media (as FestivalNativeApps' tracker does), ``POST
/repos/{repo}/issues`` for the issue. The token never appears in errors or logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com/user-attachments/assets"


class GitHubError(Exception):
    """A failed GitHub call; ``code`` is stable for the app."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code if status is None else f"{code} (HTTP {status})")
        self.code = code
        self.status = status


@dataclass
class Account:
    """What a verified token reaches."""

    login: str
    repository_id: int


def error_for(status: int, remaining: str | None, on_repository: bool = False) -> GitHubError:
    """Map a non-success status to a stable code."""
    if status == 401:
        return GitHubError("token_rejected", status)
    if status == 429 or (status == 403 and remaining == "0"):
        return GitHubError("rate_limited", status)
    if status in (403, 404):
        return GitHubError("no_repository_access" if on_repository else "no_issue_access", status)
    if status >= 500:
        return GitHubError("github_unavailable", status)
    return GitHubError("github_error", status)


class GitHubClient:
    """Calls GitHub with one token."""

    def __init__(self, session: aiohttp.ClientSession, token: str, repository: str) -> None:
        self._session = session
        self._token = token.strip()
        self.repository = repository

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        headers.update(extra or {})
        return headers

    async def _json(self, method: str, url: str, *, on_repository: bool = False, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(method, url, headers=self._headers(kwargs.pop("headers", None)),
                                             timeout=aiohttp.ClientTimeout(total=300), **kwargs) as response:
                if not 200 <= response.status < 300:
                    raise error_for(response.status, response.headers.get("x-ratelimit-remaining"), on_repository)
                data = await response.json(content_type=None)
        except GitHubError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise GitHubError("network") from err
        if not isinstance(data, dict):
            raise GitHubError("unexpected_response")
        return data

    async def verify(self) -> Account:
        """Check the token can read its user and the request repository."""
        user = await self._json("GET", f"{API}/user")
        repo = await self._json("GET", f"{API}/repos/{self.repository}", on_repository=True)
        if not isinstance(user.get("login"), str) or not isinstance(repo.get("id"), int):
            raise GitHubError("unexpected_response")
        # Reports carry screenshots of the house: never file them where anyone can read them.
        if repo.get("private") is not True:
            raise GitHubError("repository_public")
        return Account(login=user["login"], repository_id=repo["id"])

    async def upload(self, repository_id: int, name: str, content_type: str, data: bytes) -> str:
        """Upload one attachment; returns its ``https://github.com/user-attachments/…`` URL."""
        params = {"name": name, "content_type": content_type, "repository_id": str(repository_id)}
        try:
            body = await self._json("POST", UPLOADS, params=params, data=data,
                                    headers={"Content-Type": "application/octet-stream"})
        except GitHubError as err:
            if err.status is not None and 400 <= err.status < 500 and err.status not in (401, 429):
                raise GitHubError("attachment_rejected", err.status) from err
            raise
        url = body.get("url")
        if not isinstance(url, str) or not url.startswith("https://github.com/user-attachments/"):
            raise GitHubError("unexpected_response")
        return url

    async def create_issue(self, title: str, body: str, labels: list[str]) -> tuple[int, str]:
        """Create the issue; returns its number and web URL."""
        data = await self._json("POST", f"{API}/repos/{self.repository}/issues",
                                json={"title": title, "body": body, "labels": labels})
        number, url = data.get("number"), data.get("html_url")
        if not isinstance(number, int) or not isinstance(url, str):
            raise GitHubError("unexpected_response")
        return number, url
