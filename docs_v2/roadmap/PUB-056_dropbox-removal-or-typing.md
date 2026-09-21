# PUB-056: Dropbox Removal or Storage Typing

| Field | Value |
|-------|-------|
| **ID** | PUB-056 |
| **Category** | Storage |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-047, PUB-053 |

## User Story

As a platform maintainer, I want one storage backend behind one protocol, so that the web and workflow layers stop probing, casting and type-ignoring their way around a backend the orchestrator no longer offers.

## Problem

The orchestrator dropped Dropbox as a storage provider (#113), yet Publisher carries a parallel implementation: `services/storage.py` 510 lines; 22 src modules mention Dropbox; 92 test files construct `DropboxConfig` versus 26 for `ManagedStorageConfig`; about 1,900 Dropbox-specific test lines including `tools/migrate_storage.py` and its 786-line test file; `conftest.BaseDummyStorage` defaults to a `DropboxConfig`. Two protocols exist because `DropboxStorage` implements only the first (`services/storage_protocol.py:46-176`, `:183-250`). The web layer silences the gap: five identical `# type: ignore[assignment]` in `web/routers/library.py`, `isinstance(self.storage, ManagedStorage)` in `web/service.py:305`, `hasattr(source, "check_connectivity")` in `web/app.py:373`. `get_temporary_link` is a Dropbox concept in the base protocol; the workflow's timing field is still `dropbox_list_ms`. #153 (20 Sep) invested 290 lines in Dropbox retry semantics after #113 proposed removal. `requests` is undeclared but imported by a test and a script through the Dropbox SDK.

## Desired Outcome

Per the #178 decision, either the backend, its config and credential types, the migration tool, the CSP branch and the dependency are gone and one protocol remains; or the storage is typed so the five ignores, the `isinstance` and the `hasattr` disappear and `get_temporary_link` moves behind a capability. Either way, `web/` names no concrete storage class.

## Scope

**In scope (if removing, one PR per step):**
1. Rebase `conftest.BaseDummyStorage` and shared fixtures onto `ManagedStorageConfig`; mechanically fix the 92 test files with no assertion changes
2. Delete `services/storage.py`, `DropboxConfig`, `DropboxCredentials`, the Dropbox branches in `config/source.py`, `storage_factory.py`, `middleware_security.py`, the Dropbox-named cache path, the eight Dropbox test files, and `tools/migrate_storage.py` unless #178 keeps it
3. Collapse to one protocol; move `get_temporary_link` behind a capability or delete it; rename `dropbox_list_ms` (old key kept in logs for one release)
4. Drop `dropbox`; declare `requests` if the Hetzner script keeps it
5. Docs: rules, README, ARCHITECTURE stop naming Dropbox as source of truth

**In scope (if keeping):**
- `WebImageService.object_storage: ObjectStorageProtocol | None` set at construction; ignores, `isinstance` and `hasattr` removed; `get_temporary_link` in a capability protocol

**Out of scope:**
- Config model consolidation beyond the Dropbox fields (PUB-057)

## Acceptance Criteria

- AC1: Given `web/routers/library.py`, when it is searched, then it contains zero `type: ignore`
- AC2: Given `web/` and `tools/`, when the layering test runs, then no concrete storage class is named there
- AC3: Given the fixture rebase PR, when the suite runs, then every storage-facing web and workflow test passes with no assertion changed
- AC4 (removing): Given `uv.lock`, when it is searched, then `dropbox` is absent; given the protocols module, then one protocol remains
- AC5 (keeping): Given `WebImageService`, when constructed with a Dropbox backend, then `object_storage` is `None` and the library routes answer 503 with a clear message
- AC6: Given #113, when this item ships, then it is closed with the evidence

## Implementation Notes

- Sub-issue #205. Starts after Phases 1 and 3 on #177 merge.
- Step 1 is a no-behaviour-change PR and the largest diff; do it first and alone.

## Risks

- The Hetzner clone script depends on `requests` transitively; declare it or the script breaks silently.
- If a live tenant still uses Dropbox, removal must wait for its migration; #178 records this.

## Success Metrics

- `type: ignore` count in `src` drops from 11 to 6 or fewer.
- Test suite loses about 1,900 Dropbox-only lines with no loss of behaviour coverage on managed storage.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#205](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/205), [#178](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/178); closes [#113](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/113)
- [PUB-015: Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md), [PUB-023: Storage Protocol Extraction](archive/PUB-023_storage-protocol-extraction.md), [PUB-024: Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md), [PUB-031: Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md)
