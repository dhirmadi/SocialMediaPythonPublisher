# PUB-058: Workflow Stages and Layering

| Field | Value |
|-------|-------|
| **ID** | PUB-058 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Proposal |
| **Dependencies** | PUB-047, PUB-054 |

## User Story

As a platform maintainer, I want the publish pipeline to be a sequence of small stages that the CLI and the web service both run, with the layering rule enforced in both directions, so that the next correctness fix is a change to one stage rather than another branch in a 649-line function.

## Problem

`core/workflow.py:305-955` `execute()` is 649 lines with one `try` spanning 523 lines, eight nested `try`, max indent ten, and 27 locals pre-declared; `_select_image` is 169 lines. `web/service.py:746-961` `_analyze_and_caption_impl` is a 215-line second copy of analyze, caption and sidecar, and `publish_image` a 99-line second copy of publish. Both lazily import the sidecar module, both build `CaptionSpec.for_platforms`, both pick a primary caption; caption selection was rewritten three times in 48 hours (#103, #147, #134). Every weekend fix added branches inside `execute` (#139 alone +173 lines). The lease-TTL, cancellation and partial-publish invariants are enforced by one `finally` over 523 lines of state. Layering: `tests/test_layering.py` enforces only that nothing below web imports web; `core` imports concrete `services.ai`, `sidecar`, `_sanitize` and `publishers.base`; `core/models.py:79` reads the static loader lazily; `config/` imports `core.exceptions`; `utils/captions.py` and `utils/preview.py` import config, core and publishers; 46 lazy intra-package imports keep the lattice cycle-free. `ARCHITECTURE.md:11-19` claims dependency inversion the code does not practise.

## Desired Outcome

A `RunState` dataclass and seven stages (Select, Analyze, Caption, Sidecar, LeaseAndPublish, Archive, Record), each under 80 lines, with `execute` reduced to the stage list, the deadline and the `finally`. The web service runs the same stages. Six characterisation scenarios recorded before the extraction pass unchanged after it. The layering test enforces both directions and a falling ratchet on lazy imports.

## Scope

**In scope:**
- Characterisation PR first: log-event and fake-client call sequences for happy path, preview, partial publish, retry after partial, lease expired, archive failure, through the real orchestrator (`tests/test_workflow_characterisation.py`)
- `RunState`; one PR per stage moving code without behaviour change; log event names preserved
- Web service routed through Analyze, Caption, Sidecar and LeaseAndPublish, Archive, Record; duplicated code deleted; caption selection in one module
- `_select_image` split into listing, hashing and filtering
- `ConfigurationError` moved into `config/`; `utils/captions.py` and `utils/preview.py` moved under `services/`; `CaptionSpec.for_platforms` takes styles as a parameter; `WorkflowOrchestrator` receives a sidecar writer and error sanitiser by constructor
- `test_layering.py`: core imports only protocols and `publishers.base`; utils imports only utils; config does not import core; lazy-import count ratchet

**Out of scope:**
- Web app factory and routers (PUB-059)
- Typed platform captions (PUB-059), though the stages should accept the new type when it lands

## Acceptance Criteria

- AC1: Given the six characterisation scenarios, when they are recorded on `main` before any extraction, then each asserts the exact ordered log-event names and fake-client calls
- AC2: Given each stage-extraction PR, when the characterisation suite runs, then it passes with no edits
- AC3: Given `core/workflow.py` and `web/service.py` after the last PR, when function lengths are measured, then none exceeds 80 lines (ratchet test falls with each PR)
- AC4: Given the web analyze and publish paths, when they run, then they execute the same stage classes the CLI runs, and `web/service.py` contains no analyze, caption or sidecar logic of its own
- AC5: Given the extended layering test, when it runs on `main` before this item, then it fails with the exact edge list from the review; when the item is done, then it passes
- AC6: Given a future fix, when it touches `execute` or the web analyze path, then working rule 3 on #177 applies: a stage is added or edited, no branch is added

## Implementation Notes

- Two sub-issues: #207 (stages), #208 (layering). Starts only after every Phase 1 and Phase 3 PR that touches these files has merged.
- Preserve `log_json` event names byte for byte; dashboards read them.
- Stages are plain classes with `async def run(self, state)`; no framework.

## Risks

- The extraction is the largest behaviour-preserving change in the repo's history; the characterisation suite is the only protection, so it must be written adversarially (record the failure paths, not just the happy path).
- Moving `utils/captions.py` touches many imports; do it as a `git mv` with a re-export shim for one release.

## Success Metrics

- Longest function in `core/` and `web/` under 80 lines.
- Lazy intra-package imports fall from 46 to under 10.
- The next publish-path bug fix is a diff to one stage file.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#207](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/207), [#208](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/208)
- [ADR index](../03_Architecture/adr/README.md) — a new ADR for the stage pipeline is recorded with #207
- Prior fixes #96 (layering restore), #85, #139, #143, #147 (branches added to `execute`)
