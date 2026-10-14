# Fenton Home Feedback

A Home Assistant integration that files the Fenton Home app's **Report an Issue** and **Request a Feature** on GitHub, so the app never holds a GitHub token. It plays the role FestivalNativeApps' service plays for its app: the token lives here, the app sends the report over its Home Assistant sign-in, and the issue names the Home Assistant user who sent it.

Issues land in the private request repository (`SFenton/fenton-hass-requests` by default), where the triage agent on the MacBook picks them up.

## Install

1. HACS → Integrations → ⋮ → Custom repositories → add `https://github.com/SFenton/ha-fenton-feedback` (category Integration), then download **Fenton Home Feedback** and restart Home Assistant.
2. Create a fine-grained GitHub token: resource owner **SFenton**, *Only select repositories* → `fenton-hass-requests`, **Issues: Read and write**, 1 year. Pre-filled page: <https://github.com/settings/personal-access-tokens/new?name=Fenton+Home+feedback+relay&target_name=SFenton&expires_in=365&issues=write>
3. Settings → Devices & services → Add integration → **Fenton Home Feedback**, paste the token. It is checked with GitHub before it is saved. When it expires, Home Assistant asks for a new one.

## Endpoints (Home Assistant access token required)

| Call | Use |
|---|---|
| `GET /api/fenton_feedback/status` | `{available, repository}` |
| `POST /api/fenton_feedback/media?name=…&content_type=image/…\|video/…` | Raw file ≤ 10 MB (the app compresses first) → `{url}` |
| `POST /api/fenton_feedback/report` | JSON `{kind: bug\|feature, platform: ios\|ipados\|iphone-duo, title, description, repro?, expected?, diagnostics: [[label, value]], media: [{name, url, video}]}` → `201 {number, url}` |

Errors answer `{error, code}` (`invalid_form`, `title_required`, `description_required`, `field_too_long`, `too_many_attachments`, `invalid_media`, `unsupported_media`, `payload_too_large`, `rate_limited`, `not_configured`, `github_*`). Per user per ten minutes: ten reports and forty media uploads. Labels: `Bug`/`Feature`, `From App`, `iOS`/`iPadOS`/`iPhone Duo`; bodies end with `<!-- fenton-feedback:v1 -->`, typed `<!--`/`-->` are escaped so they can't hide rows or forge it, and typed `@mentions` get a zero-width joiner so they notify no one.

## Development

`python -m pytest tests/unit` (no Home Assistant needed); CI also runs `tests/ha` with `pytest-homeassistant-custom-component`, HACS and hassfest validation.
