# PUB-071: Triage the `openai` 3.x Major Upgrade

| Field | Value |
|-------|-------|
| **ID** | PUB-071 |
| **Category** | Ops |
| **Priority** | P3 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-065 (merged, #235) |

## Problem

PUB-065 deliberately held `openai` at 2.11.0. `uv lock --upgrade` offered 3.19.x, but no advisory
required it, it is a major bump on a path whose tests mock the SDK at the client boundary, and it
types against `httpx2` — which produced two real mypy errors:

```
services/ai.py:407: error: Argument "timeout" to "AsyncOpenAI" has incompatible type
"httpx._config.Timeout"; expected "float | httpx2._config.Timeout | NotGiven | None"
```

A green suite would not have proven the upgrade safe, because every OpenAI call in the tests is
mocked. Now that PUB-055's Dependabot config is live, 3.x will be proposed as an ungrouped major
(majors are deliberately ungrouped so they get individual review), so this needs a decision rather
than a reflexive merge.

## Desired Outcome

A deliberate choice: upgrade with real verification, or pin `openai<3` with the reason recorded.

## Scope

**In scope:** reviewing openai 3.x's breaking changes against `services/ai.py`; resolving the
`httpx`/`httpx2` Timeout typing; exercising vision analysis against the real API, since mocks
cannot prove it; deciding upgrade vs. pin.

**Out of scope:** changing the caption or vision prompts, or the retry layer (`_ai_retry` remains
the only retry layer per #84).

## Acceptance Criteria

- AC1: Either `openai` is on 3.x with `mypy` clean and a real vision call verified end to end, or
  `pyproject.toml` pins `openai<3` with a comment stating why — the same pattern PUB-065 used for
  `instagrapi<3`.
- AC2: The decision and its evidence are recorded in the summary, so the next Dependabot proposal
  is not re-litigated from scratch.

## Risks

- Mocked tests will pass either way. A live vision call is the only real evidence, and it costs
  tokens — budget for it rather than skipping it.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-065 (#235) · #84, #138
