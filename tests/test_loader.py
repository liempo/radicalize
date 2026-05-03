from __future__ import annotations

import json
from pathlib import Path

import pytest

from radicalize import paths
from radicalize.loader import (
    load_all_downstreams,
    load_all_upstreams,
    load_downstream,
    load_pair_file,
    load_upstream,
    remove_pairs_referencing,
    save_downstream,
    save_pair_file,
    save_upstream,
    validate_pair_references,
)
from radicalize.models import (
    Downstream,
    GoogleUpstream,
    IcsUpstream,
    Pair,
    PairFile,
)


def test_save_and_load_upstream_roundtrip(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    save_upstream(tmp_path, GoogleUpstream(id="g1", google_calendar_id="primary"))
    save_upstream(tmp_path, IcsUpstream(id="i1", external_ics_url="https://x/y.ics"))
    loaded = sorted(load_all_upstreams(tmp_path), key=lambda u: u.id)
    assert [u.id for u in loaded] == ["g1", "i1"]
    assert isinstance(load_upstream(tmp_path, "g1"), GoogleUpstream)
    assert isinstance(load_upstream(tmp_path, "i1"), IcsUpstream)


def test_save_and_load_downstream_roundtrip(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    save_downstream(tmp_path, Downstream(id="merged", href="merged-cal", sync_interval_seconds=600))
    loaded = load_downstream(tmp_path, "merged")
    assert loaded.href == "merged-cal"
    assert loaded.sync_interval_seconds == 600
    assert [d.id for d in load_all_downstreams(tmp_path)] == ["merged"]


def test_pair_file_roundtrip(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    pf = PairFile(
        pairs=[
            Pair(upstream_id="u1", downstream_id="d1", method="replace"),
            Pair(upstream_id="u2", downstream_id="d1", method="update"),
        ]
    )
    save_pair_file(tmp_path, pf)
    assert load_pair_file(tmp_path) == pf


def test_load_upstream_uses_filename_for_id(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    paths.upstream_path(tmp_path, "fromfile").write_text(
        json.dumps({"source": "ics", "external_ics_url": "https://x/y.ics"}),
        encoding="utf-8",
    )
    u = load_upstream(tmp_path, "fromfile")
    assert u.id == "fromfile"


def test_remove_pairs_by_upstream() -> None:
    pf = PairFile(
        pairs=[
            Pair(upstream_id="a", downstream_id="x"),
            Pair(upstream_id="b", downstream_id="x"),
            Pair(upstream_id="a", downstream_id="y"),
        ]
    )
    new_pf, removed = remove_pairs_referencing(pf, upstream_id="a")
    assert removed == 2
    assert [p.upstream_id for p in new_pf.pairs] == ["b"]


def test_remove_pairs_by_downstream() -> None:
    pf = PairFile(
        pairs=[
            Pair(upstream_id="a", downstream_id="x"),
            Pair(upstream_id="b", downstream_id="y"),
        ]
    )
    new_pf, removed = remove_pairs_referencing(pf, downstream_id="x")
    assert removed == 1
    assert [p.downstream_id for p in new_pf.pairs] == ["y"]


def test_validate_pair_references_reports_missing(tmp_path: Path) -> None:
    upstreams = [GoogleUpstream(id="u1")]
    downstreams = [Downstream(id="d1")]
    pf = PairFile(
        pairs=[
            Pair(upstream_id="u1", downstream_id="d1"),
            Pair(upstream_id="missing", downstream_id="d1"),
            Pair(upstream_id="u1", downstream_id="missing"),
        ]
    )
    errors = validate_pair_references(pf, upstreams, downstreams)
    assert len(errors) == 2
    assert any("missing" in e and "upstream_id" in e for e in errors)
    assert any("missing" in e and "downstream_id" in e for e in errors)


def test_load_upstream_invalid_raises(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    paths.upstream_path(tmp_path, "bad").write_text(
        json.dumps({"source": "ics"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        load_upstream(tmp_path, "bad")
