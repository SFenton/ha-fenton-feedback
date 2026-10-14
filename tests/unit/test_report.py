"""Report validation and issue composition."""

from __future__ import annotations

import pytest

from fenton_feedback.report import MARKER, ReportError, compose, parse

URL = "https://github.com/user-attachments/assets/1b2c-3d"


def bug(**extra):
    payload = {"kind": "bug", "platform": "iphone-duo", "title": "[Bug] Garage\nstuck", "description": "It <!-- hides --> things",
               "repro": "1. Open\n2. Tap", "expected": " ",
               "diagnostics": [["App", "0.1.0 (1)"], ["Locale", "a|b"]],
               "media": [{"name": "shot.png", "url": URL, "video": False}, {"name": "clip.mov", "url": URL + "e", "video": True}]}
    payload.update(extra)
    return payload


def test_bug_issue():
    title, body, labels = compose(parse(bug()), "Stephen")
    assert title == "[Bug] Garage stuck"
    assert labels == ["Bug", "From App", "iPhone Duo"]
    assert "### Description\n\nIt &lt;!-- hides --> things" in body
    assert "### Steps to Reproduce\n\n1. Open\n2. Tap" in body
    assert "Expected Behavior" not in body
    assert f"![shot.png]({URL})\n\n{URL}e" in body
    assert "| Locale | a\\|b |" in body
    assert "| Reported by | Stephen |" in body
    assert body.endswith(MARKER) and body.count(MARKER) == 1


def test_feature_ignores_bug_boxes_and_adds_prefix():
    title, body, labels = compose(parse({"kind": "feature", "platform": "ios", "title": "Dark mode", "description": "Please",
                                         "repro": "ignored"}), None)
    assert title == "[Feature] Dark mode"
    assert labels == ["Feature", "From App", "iOS"]
    assert "Steps to Reproduce" not in body and "### Media" not in body and "Reported by" not in body


@pytest.mark.parametrize("payload, code", [
    ([], "invalid_form"),
    ({"kind": "other", "platform": "ios"}, "invalid_form"),
    ({"kind": "bug", "platform": "mac", "title": "[Bug] x", "description": "y"}, "invalid_form"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] ", "description": "y"}, "title_required"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": " "}, "description_required"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": 3}, "invalid_form"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] " + "t" * 200, "description": "y"}, "field_too_long"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": "y", "media": [{"url": URL}] * 5}, "too_many_attachments"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": "y", "media": [{"url": "https://evil.example/x"}]}, "invalid_media"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": "y", "media": {}}, "invalid_form"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": "y", "diagnostics": [["a"]]}, "invalid_form"),
    ({"kind": "bug", "platform": "ios", "title": "[Bug] x", "description": "y", "diagnostics": "x"}, "invalid_form"),
])
def test_refusals(payload, code):
    with pytest.raises(ReportError) as err:
        parse(payload)
    assert err.value.code == code


def test_media_names_and_diagnostics_are_bounded():
    report = parse(bug(media=[{"name": "a[b](c).png\n", "url": URL}], diagnostics=[["Window", "x" * 400]]))
    assert report.media[0].name == "ab(c).png"
    assert len(report.diagnostics[0][1]) == 300
