---
name: voice-matching-default-review-traps
description: "#131 voice-matching derived default: validator assignment marks model_fields_set so runtime re-derivation is asymmetric; SimpleNamespace config fakes; table-breaking doc blockquotes"
metadata:
  type: project
---

Traps found reviewing `fix/131-voice-matching-default` (derived default for `features.voice_matching_enabled`).

**Why:** the "derived vs configured" distinction is encoded as membership in Pydantic's
`model_fields_set`, and plain attribute assignment adds the name to that set. So
`ApplicationConfig.default_voice_matching_from_profile` (config/schema.py) marks the field
*configured* the moment it derives it. Any later re-derivation guard
(`if "voice_matching_enabled" not in features.model_fields_set`) therefore no-ops for exactly
the tenants the feature targets — those who booted with a profile. Verified:
`ApplicationConfig(..., content=ContentConfig(voice_profile=["a"]))` ends with
`features.model_fields_set == {"voice_matching_enabled"}`. Fix shape: `discard()` in the
validator too, so "derived" is uniformly "unset".

**How to apply:**
- Any `model_fields_set` guard: check every writer of that field, including validators, not just
  the loader. Probe in a REPL; the tests usually boot a profile-less fixture and hide it.
- `publisher_v2/web/app.py` endpoints receive `service.config` that is NOT always an
  `ApplicationConfig`: `tests/web/test_admin_cookie_tenant_binding.py` stubs the tenant service
  factory with `SimpleNamespace`. Anything beyond plain attribute access (e.g. `model_fields_set`)
  500s there. `web/service.py:60` already reads features via `getattr(..., False)` for this reason.
- Markdown: a `>` blockquote inserted between rows of a table in `docs_v2/05_Configuration/
  CONFIGURATION.md` swallows the remaining rows. `tests/test_docs_feature_flags.py` only regexes
  `FEATURE_*` names, so it stays green. Put notes after the table.
- `inspect.getsource(...)` + `assert "<literal>" in source` in tests is a de-tautologied tautology:
  it asserts source text, not behaviour, and breaks on harmless refactors. Prefer extracting the
  rule into a shared helper both the builder and the test call.

**Resolved shape (merged fix, verified):** `discard()` in BOTH writers —
`ApplicationConfig.default_voice_matching_from_profile` and the web POST — so "derived" is
uniformly "unset". Verified that `model_copy(deep=True)` (web/service.py:97, how orchestrator-mode
tenant services get their config) preserves an empty `__pydantic_fields_set__`, and that
`model_copy(update=...)` does not re-run validators; so the derived-as-unset state survives into
the request path. The orchestrator drop-None rule lives in `config.source.feature_kwargs()`,
called by both the builder and the tests (removing the pop fails 12 tests).
