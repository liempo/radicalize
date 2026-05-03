from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter, ValidationError

from radicalize import paths
from radicalize.models import Downstream, Pair, PairFile, Upstream


_UPSTREAM_ADAPTER = TypeAdapter(Upstream)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {path}: {e}") from e


def load_upstream(root: Path, upstream_id: str) -> Upstream:
    path = paths.upstream_path(root, upstream_id)
    if not path.is_file():
        raise RuntimeError(f"Upstream not found: {upstream_id} ({path})")
    raw = _load_json(path)
    raw.setdefault("id", upstream_id)
    try:
        return _UPSTREAM_ADAPTER.validate_python(raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid upstream config {path}: {e}") from e


def load_downstream(root: Path, downstream_id: str) -> Downstream:
    path = paths.downstream_path(root, downstream_id)
    if not path.is_file():
        raise RuntimeError(f"Downstream not found: {downstream_id} ({path})")
    raw = _load_json(path)
    raw.setdefault("id", downstream_id)
    try:
        return Downstream.model_validate(raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid downstream config {path}: {e}") from e


def load_all_upstreams(root: Path) -> list[Upstream]:
    out: list[Upstream] = []
    for path in sorted(paths.upstream_dir(root).glob("*.json")):
        raw = _load_json(path)
        raw.setdefault("id", path.stem)
        try:
            out.append(_UPSTREAM_ADAPTER.validate_python(raw))
        except ValidationError as e:
            raise RuntimeError(f"Invalid upstream config {path}: {e}") from e
    return out


def load_all_downstreams(root: Path) -> list[Downstream]:
    out: list[Downstream] = []
    for path in sorted(paths.downstream_dir(root).glob("*.json")):
        raw = _load_json(path)
        raw.setdefault("id", path.stem)
        try:
            out.append(Downstream.model_validate(raw))
        except ValidationError as e:
            raise RuntimeError(f"Invalid downstream config {path}: {e}") from e
    return out


def load_pair_file(root: Path) -> PairFile:
    path = paths.pair_file(root)
    if not path.is_file():
        return PairFile()
    raw = _load_json(path)
    try:
        return PairFile.model_validate(raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid pair file {path}: {e}") from e


def save_pair_file(root: Path, pair_file: PairFile) -> Path:
    path = paths.pair_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(pair_file.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def save_upstream(root: Path, upstream: Upstream) -> Path:
    path = paths.upstream_path(root, upstream.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(upstream.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def save_downstream(root: Path, downstream: Downstream) -> Path:
    path = paths.downstream_path(root, downstream.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(downstream.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def remove_pairs_referencing(
    pair_file: PairFile,
    *,
    upstream_id: Optional[str] = None,
    downstream_id: Optional[str] = None,
) -> tuple[PairFile, int]:
    keep: list[Pair] = []
    removed = 0
    for p in pair_file.pairs:
        if upstream_id is not None and p.upstream_id == upstream_id:
            removed += 1
            continue
        if downstream_id is not None and p.downstream_id == downstream_id:
            removed += 1
            continue
        keep.append(p)
    return PairFile(pairs=keep), removed


def validate_pair_references(
    pair_file: PairFile,
    upstreams: list[Upstream],
    downstreams: list[Downstream],
) -> list[str]:
    """Return a list of human-readable error strings (empty if valid)."""
    errors: list[str] = []
    upstream_ids = {u.id for u in upstreams}
    downstream_ids = {d.id for d in downstreams}
    for i, p in enumerate(pair_file.pairs):
        if p.upstream_id not in upstream_ids:
            errors.append(f"pair[{i}]: unknown upstream_id {p.upstream_id!r}")
        if p.downstream_id not in downstream_ids:
            errors.append(f"pair[{i}]: unknown downstream_id {p.downstream_id!r}")
    return errors
