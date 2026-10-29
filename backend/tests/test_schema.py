from app.models import Base

EXPECTED_TABLES = {
    "projects",
    "episodes",
    "scenes",
    "shots",
    "prompt_revisions",
    "jobs",
    "job_dependencies",
    "workers",
    "render_attempts",
    "artifacts",
    "reference_assets",
    "characters",
    "character_bible_versions",
    "locations",
    "props",
    "shot_references",
    "shot_compositions",
    "shot_composition_layers",
    "visual_scene_plans",
    "events",
    "series_runs",
    "series_items",
}


def test_metadata_contains_core_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_jobs_single_target_and_active_render_guard() -> None:
    jobs = Base.metadata.tables["jobs"]
    check_names = {c.name for c in jobs.constraints if c.name}
    index_names = {i.name for i in jobs.indexes}

    assert "ck_jobs_single_target" in check_names
    assert "one_active_render_per_shot" in index_names
    assert "uq_jobs_idempotency_key" in index_names


def test_prompt_revisions_have_type_and_version() -> None:
    revisions = Base.metadata.tables["prompt_revisions"]
    unique_names = {c.name for c in revisions.constraints if c.name}

    assert "prompt_type" in revisions.columns
    assert "version" in revisions.columns
    assert "uq_prompt_revisions_shot_type_version" in unique_names


def test_artifacts_enforce_single_source() -> None:
    artifacts = Base.metadata.tables["artifacts"]
    check_names = {c.name for c in artifacts.constraints if c.name}

    assert "ck_artifacts_single_source" in check_names
    assert "ck_artifacts_source_matches_link" in check_names


def test_render_attempts_job_required_rule() -> None:
    attempts = Base.metadata.tables["render_attempts"]
    check_names = {c.name for c in attempts.constraints if c.name}

    assert "ck_render_attempts_job_required" in check_names


def test_events_sequence_and_target_rules() -> None:
    events = Base.metadata.tables["events"]
    check_names = {c.name for c in events.constraints if c.name}
    index_names = {i.name for i in events.indexes}

    assert "ck_events_target" in check_names
    assert "ck_events_progress_range" in check_names
    assert "uq_events_job_sequence" in index_names
