"""GitHub client over a fake aiohttp session."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from fenton_feedback.github import GitHubClient, GitHubError, error_for


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status, self._body, self.headers = status, body, headers or {}

    async def json(self, content_type=None):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, *replies, error=None):
        self.replies, self.calls, self.error = list(replies), [], error

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, headers, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(*self.replies.pop(0))


def run(coro):
    return asyncio.run(coro)


def test_verify_reads_user_and_repository():
    session = FakeSession((200, {"login": "SFenton"}), (200, {"id": 42, "private": True}))
    account = run(GitHubClient(session, " tok \n", "SFenton/fenton-hass-requests").verify())
    assert (account.login, account.repository_id) == ("SFenton", 42)
    assert [c[1] for c in session.calls] == ["https://api.github.com/user", "https://api.github.com/repos/SFenton/fenton-hass-requests"]
    assert session.calls[0][2]["Authorization"] == "Bearer tok"


@pytest.mark.parametrize("replies, code", [
    ([(401, {})], "token_rejected"),
    ([(200, {"login": "a"}), (404, {})], "no_repository_access"),
    ([(200, {"login": "a"}), (200, [])], "unexpected_response"),
    ([(200, {"login": "a"}), (200, {"id": 1, "private": False})], "repository_public"),
    ([(200, {"login": "a"}), (200, {"id": 1})], "repository_public"),
    ([(200, {"x": 1}), (200, {"id": 1})], "unexpected_response"),
    ([(200, ValueError("bad json"))], "network"),
])
def test_verify_failures(replies, code):
    with pytest.raises(GitHubError) as err:
        run(GitHubClient(FakeSession(*replies), "t", "o/r").verify())
    assert err.value.code == code


def test_network_errors_never_include_the_token():
    with pytest.raises(GitHubError) as err:
        run(GitHubClient(FakeSession(error=aiohttp.ClientError("boom")), "secret-token", "o/r").verify())
    assert err.value.code == "network" and "secret-token" not in str(err.value)


def test_upload_shape_and_failures():
    session = FakeSession((201, {"url": "https://github.com/user-attachments/assets/u"}))
    url = run(GitHubClient(session, "t", "o/r").upload(42, "shot.png", "image/png", b"img"))
    assert url == "https://github.com/user-attachments/assets/u"
    method, target, headers, kwargs = session.calls[0]
    assert (method, target) == ("POST", "https://uploads.github.com/user-attachments/assets")
    assert kwargs["params"] == {"name": "shot.png", "content_type": "image/png", "repository_id": "42"}
    assert kwargs["data"] == b"img" and headers["Content-Type"] == "application/octet-stream"
    for replies, code in (([(422, {})], "attachment_rejected"), ([(401, {})], "token_rejected"),
                          ([(201, {"url": "https://evil.example/u"})], "unexpected_response")):
        with pytest.raises(GitHubError) as err:
            run(GitHubClient(FakeSession(*replies), "t", "o/r").upload(1, "a.png", "image/png", b"x"))
        assert err.value.code == code


def test_create_issue():
    session = FakeSession((201, {"number": 7, "html_url": "https://github.com/o/r/issues/7"}))
    assert run(GitHubClient(session, "t", "o/r").create_issue("[Bug] X", "Body", ["Bug"])) == (7, "https://github.com/o/r/issues/7")
    assert session.calls[0][3]["json"] == {"title": "[Bug] X", "body": "Body", "labels": ["Bug"]}
    with pytest.raises(GitHubError) as err:
        run(GitHubClient(FakeSession((201, {"number": 7})), "t", "o/r").create_issue("t", "b", []))
    assert err.value.code == "unexpected_response"


def test_status_mapping():
    assert error_for(401, None).code == "token_rejected"
    assert error_for(403, "0").code == "rate_limited"
    assert error_for(429, None).code == "rate_limited"
    assert error_for(403, "9").code == "no_issue_access"
    assert error_for(404, None, on_repository=True).code == "no_repository_access"
    assert error_for(503, None).code == "github_unavailable"
    assert error_for(418, None).code == "github_error"
