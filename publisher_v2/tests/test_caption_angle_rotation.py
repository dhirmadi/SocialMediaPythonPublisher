"""PUB-051 AC1: one content angle per platform per call, rotated over a stored column.

Replaces the #82/#138 structure-directive rotation (``STRUCTURE_DIRECTIVES`` /
``classify_caption_structure`` / ``pick_structure_directive``), which reverse-
classified free caption text and so returned the same directive on every run.

Pinned contract (what these tests import):

- ``publisher_v2.utils.captions.CONTENT_ANGLES: dict[str, str]`` — ordered pool,
  key -> one-line directive naming what the caption dwells on; at least five
  entries; order is the deterministic tie-break.
- ``publisher_v2.utils.captions.pick_content_angle(history_angles, exclude=frozenset()) -> str``
  — returns a KEY. ``history_angles`` is most-recent-first; ``None`` (a legacy
  row with no stored angle) and unknown keys count as "never used"; least
  recently used wins, pool order breaks ties.
- ``AIService.create_multi_caption_pair_from_analysis`` returns
  ``(captions, sd_caption, usages, angles)`` where ``angles: dict[str, str]``
  maps every platform to the angle KEY its (final) caption was written under.
- ``CaptionStore.save_captions_batch(..., angles_by_platform=...)`` persists the
  key to the new nullable ``CaptionHistory.angle`` column, and the workflow
  reads it back for the next run's rotation.

Assertions are structural: which pool directive texts occur in the prompt that
reached the client, never the surrounding wording.
"""

from __future__ import annotations

from collections import Counter

import pytest
from caption_pipeline_fakes import (
    FakeOpenAI,
    ScriptedPublisher,
    SidecarStorage,
    install_fake_openai,
    pipeline_config,
    real_ai_service,
    user_text,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.db.caption_store import CaptionStore
from publisher_v2.db.models import Base, CaptionHistory


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


def _real_specs(**enabled: bool) -> dict[str, CaptionSpec]:
    return CaptionSpec.for_platforms(pipeline_config(**enabled))


def _analysis() -> ImageAnalysis:
    return ImageAnalysis(description="A kneeling figure in rope", mood="patient", tags=["rope"])


def _angles_in(prompt: str) -> Counter[str]:
    """Which pool directives occur in ``prompt``, and how often."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    return Counter({key: prompt.count(text) for key, text in CONTENT_ANGLES.items() if prompt.count(text)})


# History whose vocabulary shares nothing with the fake's fresh captions, so the
# similarity gate stays quiet unless a test makes a draft copy it.
_TELEGRAM_HISTORY = [
    "Rope and light across her back tonight, slow and certain, nothing hurried about it.",
    "The second wrap took longer than the first and nobody minded the wait.",
    "Hemp smells like a hardware shop and that has never once bothered anyone here.",
]
_INSTAGRAM_HISTORY = [
    "Frayed ends left untrimmed on purpose; the knot keeps its own record.",
    "Window light, a bare wall, and the patience it takes to tie well.",
]


def test_the_pool_is_a_distinct_ordered_registry_of_at_least_five() -> None:
    """Precondition for every structural count below: the directives are distinct and none contains another."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    assert len(CONTENT_ANGLES) >= 5
    texts = list(CONTENT_ANGLES.values())
    assert all(t.strip() for t in texts)
    for a in texts:
        for b in texts:
            if a is not b:
                assert a not in b, (a, b)


def test_the_structure_directive_rotation_is_gone() -> None:
    """Scope: STRUCTURE_DIRECTIVES / classify_caption_structure are deleted, not kept as a fallback."""
    import publisher_v2.utils.captions as captions_mod

    for name in ("STRUCTURE_DIRECTIVES", "classify_caption_structure", "pick_structure_directive"):
        assert not hasattr(captions_mod, name), f"{name} should be deleted (PUB-051 Scope)"


def test_pick_content_angle_is_lru_over_stored_keys_with_pool_order_ties() -> None:
    """Handoff: LRU over the stored column, NULL = never used, ties broken by pool order."""
    from publisher_v2.utils.captions import CONTENT_ANGLES, pick_content_angle

    pool = list(CONTENT_ANGLES)

    assert pick_content_angle([]) == pool[0]
    # Legacy rows (angle IS NULL) and keys from an older pool are "never used".
    assert pick_content_angle([None, None, None]) == pool[0]
    assert pick_content_angle(["declarative", None]) == pool[0]
    # Never-used candidates win, in pool order.
    assert pick_content_angle([pool[0]]) == pool[1]
    assert pick_content_angle([pool[1], pool[0]]) == pool[2]
    # Every key used: the one furthest back (history is most-recent-first) wins.
    assert pick_content_angle(list(pool)) == pool[-1]
    assert pick_content_angle([pool[-1], *pool[:-1]]) == pool[-2]
    # Exclusions remove candidates.
    assert pick_content_angle([], exclude=frozenset({pool[0]})) == pool[1]


def test_pick_content_angle_respects_platform_exclusions() -> None:
    """Scope: ``excluded_directives`` carries the per-platform exclusion contract forward against the new keys.

    Migrated from TestDirectivesFitThePlatform (#138): an angle that would
    contradict the platform brief is never picked, even when plain LRU would.
    """
    from publisher_v2.services.ai import excluded_directives
    from publisher_v2.utils.captions import CONTENT_ANGLES, pick_content_angle

    specs = [
        CaptionSpec(platform="email", style="s", hashtags="", max_length=240),
        CaptionSpec(platform="telegram", style="s", hashtags="", max_length=4096, closing="question"),
    ]
    for spec in specs:
        excluded = excluded_directives(spec)
        assert excluded <= set(CONTENT_ANGLES), f"{spec.platform}: exclusions name keys outside the pool"
        # Every allowed key used recently, every excluded key never: plain LRU would pick an excluded one.
        allowed = [k for k in CONTENT_ANGLES if k not in excluded]
        assert pick_content_angle(allowed, exclude=excluded) not in excluded


async def test_each_platform_receives_exactly_one_angle_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: one angle per platform per call — including a platform with no history yet."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    specs = _real_specs(telegram=True, instagram=True, email=True)
    fake = FakeOpenAI(list(specs))
    install_fake_openai(monkeypatch, fake)
    service = real_ai_service()
    history = {"telegram": list(_TELEGRAM_HISTORY), "instagram": list(_INSTAGRAM_HISTORY)}

    captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
        _analysis(), specs, history=history
    )

    assert set(captions) == set(specs)
    assert set(angles) == set(specs), "every platform, history or not, gets an angle"
    assert all(a in CONTENT_ANGLES for a in angles.values()), angles
    assert len(fake.caption_calls) == 1, "fresh drafts must not trip the similarity gate"
    prompt = user_text(fake.caption_calls[0])
    # Exactly the returned angles, once each per platform — no second angle, no extra directive.
    assert _angles_in(prompt) == Counter(angles.values()), prompt


async def test_angle_rotates_across_three_renders_using_stored_column(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """AC1: three real runs; each platform's angle differs across them and comes from the stored column.

    The history is seeded so reverse-classifying caption text cannot produce the
    right answer: a legacy row with no angle, then two rows whose stored angles
    are the first two pool keys. A rotation that reads the column must skip
    both on run 1; a rotation that ignores it would start at the pool head.
    """
    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.utils.captions import CONTENT_ANGLES

    pool = list(CONTENT_ANGLES)
    platforms = ["telegram", "instagram"]
    store = CaptionStore(session_factory)
    await store.save_captions_batch(
        tenant="t1", captions_by_platform={p: "Legacy row, no angle stored." for p in platforms}
    )
    await store.save_captions_batch(
        tenant="t1",
        captions_by_platform={p: "Frayed ends and a bare wall, older still." for p in platforms},
        angles_by_platform=dict.fromkeys(platforms, pool[0]),
    )
    await store.save_captions_batch(
        tenant="t1",
        captions_by_platform={p: "Hemp, a kettle, the long second wrap." for p in platforms},
        angles_by_platform=dict.fromkeys(platforms, pool[1]),
    )
    async with session_factory() as session:
        seeded_max_id = max(r.id for r in (await session.execute(select(CaptionHistory))).scalars())

    fake = FakeOpenAI(platforms)
    install_fake_openai(monkeypatch, fake)
    images = ["a.jpg", "b.jpg", "c.jpg"]
    orchestrator = WorkflowOrchestrator(
        pipeline_config(telegram=True, instagram=True),
        SidecarStorage(images),
        real_ai_service(),
        [ScriptedPublisher("telegram", [True]), ScriptedPublisher("instagram", [True])],
        tenant="t1",
        caption_store=store,
    )

    prompts_by_run: list[str] = []
    for image in images:
        before = len(fake.caption_calls)
        result = await orchestrator.execute(select_filename=image)
        assert result.success, result.error
        prompts_by_run.append("\n".join(user_text(c) for c in fake.caption_calls[before:]))

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(CaptionHistory).where(CaptionHistory.id > seeded_max_id).order_by(CaptionHistory.id)
                )
            )
            .scalars()
            .all()
        )
    for platform in platforms:
        run_angles = [r.angle for r in rows if r.platform == platform]
        assert len(run_angles) == 3, run_angles
        assert all(a in CONTENT_ANGLES for a in run_angles), run_angles
        assert len(set(run_angles)) == 3, f"{platform} repeated an angle across three runs: {run_angles}"
        assert run_angles[0] not in {pool[0], pool[1]}, "run 1 ignored the stored angle column"
        for run, angle in enumerate(run_angles):
            assert CONTENT_ANGLES[angle] in prompts_by_run[run], f"{platform} run {run}: stored angle not the one sent"


async def test_regeneration_picks_a_different_angle_than_the_rejected_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: the similarity gate's retry excludes the angle the rejected draft was written under.

    The stored angles cover every pool key, most-recent-first in pool order, so
    the draft is written under the last key — the least recently used one. That
    key stays the plain-LRU pick on the retry unless it is excluded, so a retry
    that forgets the rejected angle hands it straight back.
    """
    from publisher_v2.utils.captions import CONTENT_ANGLES

    pool = list(CONTENT_ANGLES)
    history = {"telegram": list(_TELEGRAM_HISTORY)}
    history_angles: dict[str, list[str | None]] = {"telegram": list(pool)}

    def _caption_text(call_number: int, platform: str) -> str:
        # Draft 1 copies the most recent history caption (far over the 0.45 gate); draft 2 is fresh.
        return history["telegram"][0] if call_number == 1 else "Cobalt dusk, a kettle ticking, the floor cold."

    specs = _real_specs(telegram=True)
    fake = FakeOpenAI(list(specs), caption_text=_caption_text)
    install_fake_openai(monkeypatch, fake)
    service = real_ai_service()

    _captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
        _analysis(), specs, history=history, history_angles=history_angles
    )

    assert len(fake.caption_calls) == 2, "the gate should have regenerated exactly once"
    first = _angles_in(user_text(fake.caption_calls[0]))
    retry = _angles_in(user_text(fake.caption_calls[1]))
    assert sum(first.values()) == 1, first
    assert sum(retry.values()) == 1, retry
    (rejected,) = first
    assert rejected == pool[-1], "setup: the draft should be written under the least recently used stored angle"
    (chosen,) = retry
    assert chosen != rejected, "the retry was handed the angle the rejected draft used"
    assert angles == {"telegram": chosen}, "the returned angle must be the one the kept caption was written under"


# ---------------------------------------------------------------------------
# PUB-051 critique follow-up: distinct angles within one call.
#
# Decided rule: within one call, platforms get distinct angles while the pool
# allows it. Each platform still picks the least recently used angle over its
# own stored angles; ties among never-used angles go in pool order, skipping
# angles already taken by earlier platforms in the same call. Platforms are
# processed in spec order.
# ---------------------------------------------------------------------------


async def test_platforms_in_one_call_get_distinct_angles_while_pool_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three platforms, empty history: three different angles, one angle line per platform in the prompt."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    specs = _real_specs(telegram=True, instagram=True, email=True)
    assert len(specs) == 3 and len(CONTENT_ANGLES) >= len(specs), "setup: the pool must allow distinct angles"
    fake = FakeOpenAI(list(specs))
    install_fake_openai(monkeypatch, fake)

    _captions, _sd, _usages, angles = await real_ai_service().create_multi_caption_pair_from_analysis(
        _analysis(), specs
    )

    assert set(angles) == set(specs)
    assert all(a in CONTENT_ANGLES for a in angles.values()), angles
    assert len(set(angles.values())) == len(specs), f"platforms share an angle within one call: {angles}"
    assert len(fake.caption_calls) == 1
    prompt = user_text(fake.caption_calls[0])
    hits = _angles_in(prompt)
    assert sum(hits.values()) == len(specs), f"expected one angle line per platform, got {dict(hits)}"
    assert hits == Counter(angles.values()), prompt


async def test_angles_stay_distinct_across_runs_on_a_fresh_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Four runs on a fresh tenant, each run's angles fed back as the most recent stored history.

    Every run: distinct angles across platforms, and every platform's angle
    differs from the one it had on the previous run.
    """
    from publisher_v2.utils.captions import CONTENT_ANGLES

    specs = _real_specs(telegram=True, instagram=True, email=True)
    fake = FakeOpenAI(list(specs))
    install_fake_openai(monkeypatch, fake)
    service = real_ai_service()

    history_angles: dict[str, list[str | None]] = {p: [] for p in specs}
    runs: list[dict[str, str]] = []
    for _run in range(4):
        _captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
            _analysis(), specs, history_angles={p: list(v) for p, v in history_angles.items()}
        )
        assert set(angles) == set(specs)
        assert all(a in CONTENT_ANGLES for a in angles.values()), angles
        runs.append(dict(angles))
        for platform, angle in angles.items():
            history_angles[platform].insert(0, angle)  # most-recent-first

    for run, angles in enumerate(runs, 1):
        assert len(set(angles.values())) == len(specs), f"run {run}: platforms share an angle: {angles}"
    for run in range(1, len(runs)):
        for platform in specs:
            assert runs[run][platform] != runs[run - 1][platform], (
                f"{platform} kept angle {runs[run][platform]!r} from run {run} to run {run + 1}: {runs}"
            )


async def test_regeneration_offender_avoids_the_other_platforms_current_angle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviewer W1: the retry's soft distinct-angle rule still holds for the offender.

    Two platforms, only telegram offends. The stored angles are built so that
    plain LRU for telegram on the retry — its rejected angle pushed to the front
    of its history and excluded — lands exactly on instagram's current angle.
    Only the ``avoid`` preference steers telegram off it.
    """
    from publisher_v2.utils.captions import CONTENT_ANGLES, pick_content_angle

    pool = list(CONTENT_ANGLES)
    history = {"telegram": list(_TELEGRAM_HISTORY), "instagram": list(_INSTAGRAM_HISTORY)}
    # telegram: every key used, pool order most-recent-first -> its draft goes under pool[-1] and,
    # once that is rejected, plain LRU picks pool[-2].
    # instagram: every key but pool[-2] used -> pool[-2] is its only never-used key, so it takes it.
    history_angles: dict[str, list[str | None]] = {
        "telegram": list(pool),
        "instagram": [k for k in pool if k != pool[-2]],
    }

    def _caption_text(call_number: int, platform: str) -> str:
        if platform == "telegram" and call_number == 1:
            return history["telegram"][0]  # far over the similarity gate
        return f"Cobalt dusk over the {platform} kettle, the floor cold, draft {call_number}."

    specs = _real_specs(telegram=True, instagram=True)
    fake = FakeOpenAI(list(specs), caption_text=_caption_text)
    install_fake_openai(monkeypatch, fake)

    _captions, _sd, _usages, angles = await real_ai_service().create_multi_caption_pair_from_analysis(
        _analysis(), specs, history=history, history_angles=history_angles
    )

    assert len(fake.caption_calls) == 2, "only telegram should offend, and the gate regenerates exactly once"
    first = _angles_in(user_text(fake.caption_calls[0]))
    assert first == Counter({pool[-1]: 1, pool[-2]: 1}), f"setup: unexpected first-draft angles {dict(first)}"
    rejected = pool[-1]
    other = angles["instagram"]
    assert other == pool[-2], "setup: the non-offender should keep the angle it was first given"
    # The fixture forces the collision: without the soft rule, the retry pick IS the other platform's angle.
    assert pick_content_angle([rejected, *history_angles["telegram"]], frozenset({rejected})) == other

    new = angles["telegram"]
    assert new != rejected, "the retry was handed the angle the rejected draft used"
    assert new != other, f"the offender's retry angle collides with instagram's current angle {other!r}"
    retry = _angles_in(user_text(fake.caption_calls[1]))
    assert retry == Counter({new: 1, other: 1}), f"retry prompt angles {dict(retry)} != returned {angles}"


# ---------------------------------------------------------------------------
# PUB-051 critique follow-up: angle starvation under the production window.
#
# Decided rule: the angle history is read at least as deep as the pool —
# ``max(window_size, len(CONTENT_ANGLES))`` rows per platform — so the LRU can
# see every angle it has used. The caption-TEXT history handed to the prompt
# stays capped at ``window_size``. With the old ``limit=window_size`` (3) and a
# pool of six, the rotation cycled through only the first four angles forever.
# ---------------------------------------------------------------------------


def _disjoint_caption_text(call_number: int, platform: str) -> str:
    """Captions sharing no word with any other call, so the similarity gate never regenerates.

    A regeneration re-picks the offender's angle; keeping the gate quiet means
    every stored angle is the plain rotation pick under test.
    """
    return " ".join(f"w{call_number}x{platform}x{i}" for i in range(8)) + "."


async def test_production_window_rotation_uses_every_angle_over_twenty_runs(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Twenty real publishes, three platforms, shipped ``window_size``: every platform uses every angle twice.

    Real WorkflowOrchestrator, AIService and CaptionStore; only OpenAI, storage
    and the publishers are faked. Also pins that the caption-text history the
    caption stage receives stays capped at ``window_size`` per platform.
    """
    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.utils.captions import CONTENT_ANGLES

    window = get_static_config().ai_prompts.caption_history.window_size
    platforms = ["telegram", "instagram", "email"]
    store = CaptionStore(session_factory)
    fake = FakeOpenAI(platforms, caption_text=_disjoint_caption_text)
    install_fake_openai(monkeypatch, fake)
    ai = real_ai_service()

    received_history: list[dict[str, list[str]] | None] = []
    real_multi = ai.create_multi_caption_pair_from_analysis

    async def _spy(*args, **kwargs):
        history = kwargs.get("history")
        received_history.append({p: list(v) for p, v in history.items()} if isinstance(history, dict) else history)
        return await real_multi(*args, **kwargs)

    ai.create_multi_caption_pair_from_analysis = _spy  # type: ignore[method-assign]

    images = [f"img{i:02d}.jpg" for i in range(20)]
    orchestrator = WorkflowOrchestrator(
        pipeline_config(telegram=True, instagram=True, email=True),
        SidecarStorage(images),
        ai,
        [ScriptedPublisher(p, [True]) for p in platforms],
        tenant="t1",
        caption_store=store,
    )

    for image in images:
        result = await orchestrator.execute(select_filename=image)
        assert result.success, result.error

    assert len(fake.caption_calls) == 20, "setup: the similarity gate regenerated; angles are not plain rotation picks"
    async with session_factory() as session:
        rows = (await session.execute(select(CaptionHistory).order_by(CaptionHistory.id))).scalars().all()
    for platform in platforms:
        used = Counter(r.angle for r in rows if r.platform == platform)
        assert sum(used.values()) == 20, f"{platform}: expected 20 stored rows, got {dict(used)}"
        starved = {k: used.get(k, 0) for k in CONTENT_ANGLES if used.get(k, 0) < 2}
        assert not starved, (
            f"{platform}: angles used fewer than twice over 20 runs with window_size={window}: {starved}; "
            f"distribution {dict(used)}"
        )

    assert len(received_history) == 20
    for run, history in enumerate(received_history):
        for platform, texts in (history or {}).items():
            assert len(texts) <= window, (
                f"run {run} {platform}: caption-text history is {len(texts)} deep; it must stay at window_size={window}"
            )
