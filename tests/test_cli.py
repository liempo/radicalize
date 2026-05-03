from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

import pytest
from typer.testing import CliRunner

from radicalize import paths
from radicalize.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure tests never accidentally read the user's RADICALIZE_DATA."""
    monkeypatch.delenv("RADICALIZE_DATA", raising=False)


def _invoke(
    runner: CliRunner,
    args: Sequence[str],
    *,
    input: Optional[str] = None,
    env: Optional[dict] = None,
):
    return runner.invoke(app, list(args), input=input, env=env, catch_exceptions=False)


def _data_args(data_dir: Path, *rest: str) -> list[str]:
    return ["--data-dir", str(data_dir), *rest]


# ---------------------------------------------------------------------------
# init / reset / data-dir resolution
# ---------------------------------------------------------------------------


def test_init_creates_layout(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, _data_args(tmp_path, "init"))
    assert result.exit_code == 0
    assert paths.is_initialized(tmp_path)
    assert (tmp_path / ".env.example").is_file()


def test_init_idempotent(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "init"))
    result = _invoke(runner, _data_args(tmp_path, "init"))
    assert result.exit_code == 0
    assert paths.is_initialized(tmp_path)


def test_global_data_dir_before_subcommand(runner: CliRunner, tmp_path: Path) -> None:
    """`radicalize --data-dir <path> upstream list` should resolve to <path>."""
    result = _invoke(runner, ["--data-dir", str(tmp_path), "upstream", "list"])
    assert result.exit_code == 0
    assert paths.is_initialized(tmp_path)
    assert "(no upstreams)" in result.stdout


def test_per_command_data_dir(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, ["upstream", "list", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "(no upstreams)" in result.stdout


def test_short_data_dir_flag(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, ["-d", str(tmp_path), "init"])
    assert result.exit_code == 0
    assert paths.is_initialized(tmp_path)


def test_radicalize_data_env_is_used(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, ["init"], env={"RADICALIZE_DATA": str(tmp_path)})
    assert result.exit_code == 0
    assert paths.is_initialized(tmp_path)


def test_per_command_data_dir_overrides_global(runner: CliRunner, tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    result = _invoke(
        runner,
        ["--data-dir", str(a), "upstream", "list", "--data-dir", str(b)],
    )
    assert result.exit_code == 0
    assert paths.is_initialized(b)
    assert not paths.is_initialized(a)


def test_root_help_works(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--data-dir" in result.stdout
    assert "init" in result.stdout
    assert "upstream" in result.stdout


def test_reset_aborts_when_user_says_no(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "init"))
    (tmp_path / "marker.txt").write_text("keep me", encoding="utf-8")
    result = runner.invoke(app, _data_args(tmp_path, "reset"), input="n\n")
    assert result.exit_code != 0
    assert (tmp_path / "marker.txt").exists()


def test_reset_yes_clears_state(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "init"))
    (tmp_path / "extra.txt").write_text("bye", encoding="utf-8")
    result = _invoke(runner, _data_args(tmp_path, "reset", "--yes"))
    assert result.exit_code == 0
    assert not (tmp_path / "extra.txt").exists()
    assert paths.is_initialized(tmp_path)


# ---------------------------------------------------------------------------
# upstream commands
# ---------------------------------------------------------------------------


def test_upstream_add_google_non_interactive(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(
        runner,
        _data_args(
            tmp_path,
            "upstream", "add", "work",
            "--source", "google",
            "--google-calendar-id", "primary",
            "--name", "Work calendar",
            "--no-oauth",
        ),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads((paths.upstream_path(tmp_path, "work")).read_text(encoding="utf-8"))
    assert saved["source"] == "google"
    assert saved["google_calendar_id"] == "primary"
    assert saved["name"] == "Work calendar"


def test_upstream_add_ics_non_interactive(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(
        runner,
        _data_args(
            tmp_path,
            "upstream", "add", "holidays",
            "--source", "ics",
            "--ics-url", "https://example.com/h.ics",
        ),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads(paths.upstream_path(tmp_path, "holidays").read_text(encoding="utf-8"))
    assert saved["source"] == "ics"
    assert saved["external_ics_url"] == "https://example.com/h.ics"


def test_upstream_add_ics_requires_url(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        _data_args(tmp_path, "upstream", "add", "holidays", "--source", "ics"),
    )
    assert result.exit_code != 0
    assert "--ics-url" in (result.stderr or "") + (result.stdout or "")


def test_upstream_add_duplicate_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "work",
            "--source", "google", "--no-oauth",
        ),
    )
    result = runner.invoke(
        app,
        _data_args(
            tmp_path, "upstream", "add", "work",
            "--source", "google", "--no-oauth",
        ),
    )
    assert result.exit_code == 1
    assert "already exists" in (result.stderr or result.stdout)


def test_upstream_add_invalid_source_is_usage_error(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        _data_args(tmp_path, "upstream", "add", "x", "--source", "ical"),
    )
    assert result.exit_code == 2


def test_upstream_add_interactive_uses_prompt(runner: CliRunner, tmp_path: Path) -> None:
    """Interactive wizard works when no flags are passed: choose google, no OAuth prompt accepted as 'no'."""
    result = runner.invoke(
        app,
        _data_args(tmp_path, "upstream", "add", "work"),
        input="\n".join(["1", "Work", "primary", "n"]) + "\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads(paths.upstream_path(tmp_path, "work").read_text(encoding="utf-8"))
    assert saved["source"] == "google"
    assert saved["name"] == "Work"


def test_upstream_edit_partial_keeps_other_fields(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "work",
            "--source", "google", "--google-calendar-id", "primary",
            "--name", "Original", "--no-oauth",
        ),
    )
    result = _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "edit", "work",
            "--name", "Renamed", "--no-oauth",
        ),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads(paths.upstream_path(tmp_path, "work").read_text(encoding="utf-8"))
    assert saved["name"] == "Renamed"
    assert saved["google_calendar_id"] == "primary"


def test_upstream_edit_missing_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        _data_args(tmp_path, "upstream", "edit", "ghost", "--name", "x", "--no-oauth"),
    )
    assert result.exit_code == 1
    assert "not found" in (result.stderr or result.stdout)


def test_upstream_remove_unknown_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, _data_args(tmp_path, "upstream", "remove", "ghost"))
    assert result.exit_code == 1
    assert "not found" in (result.stderr or result.stdout)


def test_upstream_remove_cleans_pair_entries(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "u1",
            "--source", "ics", "--ics-url", "https://example.com/h.ics",
        ),
    )
    _invoke(
        runner,
        _data_args(
            tmp_path, "downstream", "add", "d1",
            "--non-interactive",
        ),
    )
    _invoke(
        runner,
        _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1"),
    )
    result = _invoke(runner, _data_args(tmp_path, "upstream", "remove", "u1"))
    assert result.exit_code == 0
    assert "Removed" in result.stdout
    pair_data = json.loads(paths.pair_file(tmp_path).read_text(encoding="utf-8"))
    assert pair_data["pairs"] == []


def test_upstream_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, _data_args(tmp_path, "upstream", "list"))
    assert result.exit_code == 0
    assert "(no upstreams)" in result.stdout


def test_upstream_list_lists_entries(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "work",
            "--source", "google", "--no-oauth",
        ),
    )
    result = _invoke(runner, _data_args(tmp_path, "upstream", "list"))
    assert result.exit_code == 0
    assert "work" in result.stdout
    assert "google" in result.stdout


# ---------------------------------------------------------------------------
# downstream commands
# ---------------------------------------------------------------------------


def test_downstream_add_non_interactive(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(
        runner,
        _data_args(
            tmp_path, "downstream", "add", "merged",
            "--name", "Merged", "--href", "merged-cal",
            "--sync-interval-seconds", "900",
        ),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads(paths.downstream_path(tmp_path, "merged").read_text(encoding="utf-8"))
    assert saved["name"] == "Merged"
    assert saved["href"] == "merged-cal"
    assert saved["sync_interval_seconds"] == 900


def test_downstream_add_with_only_id_via_non_interactive_flag(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(
        runner,
        _data_args(tmp_path, "downstream", "add", "minimal", "--non-interactive"),
    )
    assert result.exit_code == 0
    saved = json.loads(paths.downstream_path(tmp_path, "minimal").read_text(encoding="utf-8"))
    assert saved["id"] == "minimal"
    assert "name" not in saved
    assert "href" not in saved


def test_downstream_add_invalid_interval_is_usage_error(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        _data_args(
            tmp_path, "downstream", "add", "bad",
            "--sync-interval-seconds", "0",
        ),
    )
    assert result.exit_code == 2


def test_downstream_add_duplicate_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "downstream", "add", "merged", "--non-interactive"))
    result = runner.invoke(
        app,
        _data_args(tmp_path, "downstream", "add", "merged", "--non-interactive"),
    )
    assert result.exit_code == 1
    assert "already exists" in (result.stderr or result.stdout)


def test_downstream_edit_partial_field(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "downstream", "add", "merged",
            "--name", "Original", "--href", "h",
        ),
    )
    result = _invoke(
        runner,
        _data_args(tmp_path, "downstream", "edit", "merged", "--name", "New"),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    saved = json.loads(paths.downstream_path(tmp_path, "merged").read_text(encoding="utf-8"))
    assert saved["name"] == "New"
    assert saved["href"] == "h"


def test_downstream_remove_cleans_pair_entries(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "u1",
            "--source", "ics", "--ics-url", "https://example.com/h.ics",
        ),
    )
    _invoke(runner, _data_args(tmp_path, "downstream", "add", "d1", "--non-interactive"))
    _invoke(runner, _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1"))
    result = _invoke(runner, _data_args(tmp_path, "downstream", "remove", "d1"))
    assert result.exit_code == 0
    pair_data = json.loads(paths.pair_file(tmp_path).read_text(encoding="utf-8"))
    assert pair_data["pairs"] == []


def test_downstream_list_lists_entries(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "downstream", "add", "merged", "--non-interactive"))
    result = _invoke(runner, _data_args(tmp_path, "downstream", "list"))
    assert result.exit_code == 0
    assert "merged" in result.stdout


# ---------------------------------------------------------------------------
# pair commands
# ---------------------------------------------------------------------------


def _setup_pair_prereqs(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "u1",
            "--source", "ics", "--ics-url", "https://example.com/h.ics",
        ),
    )
    _invoke(runner, _data_args(tmp_path, "downstream", "add", "d1", "--non-interactive"))


def test_pair_add_default_method_is_update(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    result = _invoke(
        runner,
        _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1"),
    )
    assert result.exit_code == 0
    pair_data = json.loads(paths.pair_file(tmp_path).read_text(encoding="utf-8"))
    assert pair_data["pairs"] == [
        {"upstream_id": "u1", "downstream_id": "d1", "method": "update"}
    ]


def test_pair_add_replace_method(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    result = _invoke(
        runner,
        _data_args(
            tmp_path, "pair", "add",
            "--upstream", "u1", "--downstream", "d1",
            "--method", "replace",
        ),
    )
    assert result.exit_code == 0
    pair_data = json.loads(paths.pair_file(tmp_path).read_text(encoding="utf-8"))
    assert pair_data["pairs"][0]["method"] == "replace"


def test_pair_add_invalid_method_returns_2(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    result = runner.invoke(
        app,
        _data_args(
            tmp_path, "pair", "add",
            "--upstream", "u1", "--downstream", "d1",
            "--method", "merge",
        ),
    )
    assert result.exit_code == 2


def test_pair_add_unknown_upstream_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(runner, _data_args(tmp_path, "downstream", "add", "d1", "--non-interactive"))
    result = runner.invoke(
        app,
        _data_args(tmp_path, "pair", "add", "--upstream", "ghost", "--downstream", "d1"),
    )
    assert result.exit_code == 1


def test_pair_add_unknown_downstream_returns_1(runner: CliRunner, tmp_path: Path) -> None:
    _invoke(
        runner,
        _data_args(
            tmp_path, "upstream", "add", "u1",
            "--source", "ics", "--ics-url", "https://example.com/h.ics",
        ),
    )
    result = runner.invoke(
        app,
        _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "ghost"),
    )
    assert result.exit_code == 1


def test_pair_remove_no_match_is_noop(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    result = _invoke(
        runner,
        _data_args(tmp_path, "pair", "remove", "--upstream", "u1", "--downstream", "d1"),
    )
    assert result.exit_code == 0
    assert "No matching pair" in result.stdout


def test_pair_remove_matches(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    _invoke(runner, _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1"))
    _invoke(runner, _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1", "--method", "replace"))
    result = _invoke(
        runner,
        _data_args(tmp_path, "pair", "remove", "--upstream", "u1", "--downstream", "d1"),
    )
    assert result.exit_code == 0
    pair_data = json.loads(paths.pair_file(tmp_path).read_text(encoding="utf-8"))
    assert pair_data["pairs"] == []


def test_pair_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    result = _invoke(runner, _data_args(tmp_path, "pair", "list"))
    assert result.exit_code == 0
    assert "(no pairs)" in result.stdout


def test_pair_list_warns_on_orphan(runner: CliRunner, tmp_path: Path) -> None:
    _setup_pair_prereqs(runner, tmp_path)
    _invoke(runner, _data_args(tmp_path, "pair", "add", "--upstream", "u1", "--downstream", "d1"))
    pair_path = paths.pair_file(tmp_path)
    pair_path.write_text(
        json.dumps(
            {"pairs": [{"upstream_id": "ghost", "downstream_id": "d1", "method": "update"}]}
        ),
        encoding="utf-8",
    )
    result = _invoke(runner, _data_args(tmp_path, "pair", "list"))
    assert result.exit_code == 0
    assert "warn:" in result.stderr
    assert "ghost" in result.stderr


# ---------------------------------------------------------------------------
# sync (mocked) — we only need to verify CLI wiring + exit code propagation.
# ---------------------------------------------------------------------------


def test_sync_calls_runner_and_exits_0(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict = {}

    def fake_sync_all(root: Path) -> None:
        called["root"] = root

    import radicalize.runner as runner_module

    monkeypatch.setattr(runner_module, "sync_all", fake_sync_all)
    result = _invoke(runner, _data_args(tmp_path, "sync"))
    assert result.exit_code == 0
    assert called["root"] == tmp_path.resolve()


def test_sync_propagates_runtime_failure_as_exit_1(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(root: Path) -> None:
        raise RuntimeError("boom")

    import radicalize.runner as runner_module

    monkeypatch.setattr(runner_module, "sync_all", boom)
    result = runner.invoke(app, _data_args(tmp_path, "sync"))
    assert result.exit_code == 1
    assert "boom" in (result.stderr or result.stdout)
