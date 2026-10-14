"""Constants for Fenton Home Feedback."""

from __future__ import annotations

DOMAIN = "fenton_feedback"

CONF_REPOSITORY = "repository"
DEFAULT_REPOSITORY = "SFenton/fenton-hass-requests"

#: GitHub's user-attachment limit; the app shrinks media to fit before uploading.
MAX_MEDIA_BYTES = 10 * 1024 * 1024
#: Attachments per report.
MAX_ATTACHMENTS = 4
#: Title, prefix included (UTF-16 units, as the app counts).
MAX_TITLE = 200
#: Per text box.
MAX_BOX = 10_000
#: Diagnostics rows and each value's length.
MAX_DIAGNOSTICS = 20
MAX_DIAGNOSTIC_VALUE = 300
#: Reports per user per window.
RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 600

API_STATUS = "/api/fenton_feedback/status"
API_MEDIA = "/api/fenton_feedback/media"
API_REPORT = "/api/fenton_feedback/report"
