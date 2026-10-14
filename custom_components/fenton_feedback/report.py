"""Validation and issue composition for app reports (no Home Assistant imports, so tests run anywhere).

Ported from the app's former ``FeedbackIssue.compose`` (SFenton/Fenton-HASS-Native): the server now owns the issue
format, as FestivalNativeApps' service does for its app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .const import MAX_ATTACHMENTS, MAX_BOX, MAX_DIAGNOSTIC_VALUE, MAX_DIAGNOSTICS, MAX_TITLE

#: Hidden marker ending every in-app report; the triage agent keys on it. Typed text can't forge it.
MARKER = "<!-- fenton-feedback:v1 -->"
FROM_APP_LABEL = "From App"
KINDS = {"bug": ("[Bug] ", "Bug"), "feature": ("[Feature] ", "Feature")}
PLATFORMS = {"ios": "iOS", "ipados": "iPadOS", "iphone-duo": "iPhone Duo"}
ATTACHMENT_URL = re.compile(r"^https://github\.com/user-attachments/(?:assets|files)/[A-Za-z0-9-]+$")


class ReportError(ValueError):
    """A report the server refuses; ``code`` is stable for the app to map to its own copy."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Media:
    """One uploaded attachment."""

    name: str
    url: str
    video: bool


@dataclass
class Report:
    """A validated report."""

    kind: str
    platform: str
    title: str
    description: str
    repro: str = ""
    expected: str = ""
    diagnostics: list[tuple[str, str]] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)


def utf16_len(text: str) -> int:
    """Length in UTF-16 units, as Swift's `utf16.count`."""
    return len(text.encode("utf-16-le")) // 2


def one_line(text: str) -> str:
    """Collapse whitespace and newlines to single spaces."""
    return " ".join(text.split())


#: Zero-width joiner placed after `@` so typed mentions don't notify anyone.
ZWJ = "\u200d"


def escaped(text: str) -> str:
    """Make typed text inert: HTML comment openers and closers can't hide content or forge the marker, and
    `@name` mentions don't notify (a zero-width joiner after the `@`)."""
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return re.sub(r"@(?=[A-Za-z0-9])", "@" + ZWJ, text)


def table_cell(text: str) -> str:
    """A value safe inside a Markdown table cell."""
    return escaped(one_line(text)).replace("|", "\\|")


def _text(payload: dict[str, Any], key: str, limit: int, required: bool = False) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ReportError("invalid_form")
    value = value.strip()
    if required and not value:
        raise ReportError(f"{key}_required")
    if utf16_len(value) > limit:
        raise ReportError("field_too_long")
    return value


def parse(payload: Any) -> Report:
    """Validate the app's JSON report.

    Raises:
        ReportError: with ``invalid_form``, ``title_required``, ``description_required``, ``field_too_long``,
            ``too_many_attachments`` or ``invalid_media``.
    """
    if not isinstance(payload, dict):
        raise ReportError("invalid_form")
    kind = payload.get("kind")
    platform = payload.get("platform")
    if kind not in KINDS or platform not in PLATFORMS:
        raise ReportError("invalid_form")
    prefix = KINDS[kind][0]
    title = _text(payload, "title", MAX_TITLE)
    bare = prefix.strip()
    body = one_line(title[len(bare):] if title.startswith(bare) else title)
    if not body:
        raise ReportError("title_required")
    report = Report(
        kind=kind,
        platform=platform,
        title=prefix + body,
        description=_text(payload, "description", MAX_BOX, required=True),
    )
    if kind == "bug":
        report.repro = _text(payload, "repro", MAX_BOX)
        report.expected = _text(payload, "expected", MAX_BOX)
    rows = payload.get("diagnostics", [])
    if not isinstance(rows, list) or len(rows) > MAX_DIAGNOSTICS:
        raise ReportError("invalid_form")
    for row in rows:
        if not (isinstance(row, list) and len(row) == 2 and all(isinstance(x, str) for x in row)):
            raise ReportError("invalid_form")
        report.diagnostics.append((one_line(row[0])[:60], one_line(row[1])[:MAX_DIAGNOSTIC_VALUE]))
    media = payload.get("media", [])
    if not isinstance(media, list):
        raise ReportError("invalid_form")
    if len(media) > MAX_ATTACHMENTS:
        raise ReportError("too_many_attachments")
    for item in media:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not ATTACHMENT_URL.match(item["url"]):
            raise ReportError("invalid_media")
        name = one_line(str(item.get("name", "attachment")))[:120] or "attachment"
        name = escaped(name.replace("]", "").replace("[", "")) or "attachment"
        report.media.append(Media(name=name, url=item["url"], video=bool(item.get("video"))))
    return report


def compose(report: Report, reporter: str | None) -> tuple[str, str, list[str]]:
    """The issue for a report: title, Markdown body and labels.

    Sections for each filled box, ``### Media`` (images inline, videos as bare URLs, which GitHub plays), a
    ``### Diagnostics`` table with the Home Assistant user who sent it, then the marker.
    """
    sections: list[str] = []

    def add(heading: str, text: str) -> None:
        if text:
            sections.append(f"### {heading}\n\n{escaped(text)}")

    add("Description", report.description)
    if report.kind == "bug":
        add("Steps to Reproduce", report.repro)
        add("Expected Behavior", report.expected)
    if report.media:
        lines = [m.url if m.video else f"![{m.name}]({m.url})" for m in report.media]
        sections.append("### Media\n\n" + "\n\n".join(lines))
    rows = list(report.diagnostics)
    if reporter:
        rows.append(("Reported by", reporter))
    table = "\n".join(f"| {table_cell(label)} | {table_cell(value)} |" for label, value in rows)
    sections.append("### Diagnostics\n\n| | |\n|---|---|\n" + table)
    sections.append(f"<sub>Filed from the app's Settings through Home Assistant.</sub>\n{MARKER}")
    labels = [KINDS[report.kind][1], FROM_APP_LABEL, PLATFORMS[report.platform]]
    return escaped(one_line(report.title)), "\n\n".join(sections), labels
