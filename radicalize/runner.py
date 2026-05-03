from __future__ import annotations

import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path

from radicalize import paths, pair_merge
from radicalize.envconfig import RadicaleSettings, load_radicale_settings
from radicalize.loader import (
    load_all_downstreams,
    load_all_upstreams,
    load_pair_file,
    validate_pair_references,
)
from radicalize.models import (
    Downstream,
    GoogleUpstream,
    IcsUpstream,
    Pair,
    Upstream,
    display_name,
)
from radicalize.radicale_client import collection_url, get_collection, put_collection
from radicalize.sync.google import fetch_google_bytes
from radicalize.sync.ics import fetch_ics_bytes


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def fetch_upstream_bytes(data_dir: Path, upstream: Upstream) -> bytes:
    if isinstance(upstream, GoogleUpstream):
        return fetch_google_bytes(data_dir, upstream)
    if isinstance(upstream, IcsUpstream):
        return fetch_ics_bytes(upstream)
    raise RuntimeError(f"Unknown upstream type: {type(upstream).__name__}")


def _group_pairs_by_downstream(pairs: list[Pair]) -> "OrderedDict[str, list[Pair]]":
    grouped: "OrderedDict[str, list[Pair]]" = OrderedDict()
    for p in pairs:
        grouped.setdefault(p.downstream_id, []).append(p)
    return grouped


def sync_downstream(
    data_dir: Path,
    settings: RadicaleSettings,
    downstream: Downstream,
    pairs: list[Pair],
    upstreams_by_id: dict[str, Upstream],
) -> None:
    if not pairs:
        print(f"{_ts()} downstream[{downstream.id}]: no pairs, skipping")
        return

    cal_name = display_name(downstream)
    url = collection_url(settings, downstream)

    existing = get_collection(url, settings)
    working = pair_merge.parse_calendar(existing, cal_name)

    for p in pairs:
        upstream = upstreams_by_id.get(p.upstream_id)
        if upstream is None:
            print(
                f"{_ts()} downstream[{downstream.id}] pair: unknown upstream "
                f"{p.upstream_id!r}, skipping",
                file=sys.stderr,
            )
            continue
        try:
            raw = fetch_upstream_bytes(data_dir, upstream)
        except Exception as e:
            print(
                f"{_ts()} downstream[{downstream.id}] fetch upstream[{upstream.id}] failed: {e}",
                file=sys.stderr,
            )
            traceback.print_exc()
            continue

        upstream_cal = pair_merge.parse_calendar(raw)
        if p.method == "replace":
            removed, added = pair_merge.apply_replace(working, upstream_cal, upstream.id)
            print(
                f"{_ts()} downstream[{downstream.id}] <- {upstream.id} "
                f"replace: -{removed} +{added}"
            )
        else:
            updated, added = pair_merge.apply_update(working, upstream_cal, upstream.id)
            print(
                f"{_ts()} downstream[{downstream.id}] <- {upstream.id} "
                f"update: ~{updated} +{added}"
            )

    body = pair_merge.serialize(working, cal_name)
    put_collection(url, settings, body)
    print(f"{_ts()} downstream[{downstream.id}]: PUT -> {url}")


def _load_world(data_dir: Path):
    upstreams = load_all_upstreams(data_dir)
    downstreams = load_all_downstreams(data_dir)
    pair_file = load_pair_file(data_dir)
    errors = validate_pair_references(pair_file, upstreams, downstreams)
    for err in errors:
        print(f"radicalize: {err}", file=sys.stderr)
    upstreams_by_id = {u.id: u for u in upstreams}
    downstreams_by_id = {d.id: d for d in downstreams}
    return upstreams_by_id, downstreams_by_id, pair_file


def sync_all(data_dir: Path) -> None:
    paths.ensure_layout(data_dir)
    settings = load_radicale_settings(data_dir)
    upstreams_by_id, downstreams_by_id, pair_file = _load_world(data_dir)
    grouped = _group_pairs_by_downstream(pair_file.pairs)
    for downstream_id, pairs in grouped.items():
        downstream = downstreams_by_id.get(downstream_id)
        if downstream is None:
            print(
                f"radicalize: skipping unknown downstream {downstream_id!r} "
                "(referenced in pair.json)",
                file=sys.stderr,
            )
            continue
        try:
            sync_downstream(data_dir, settings, downstream, pairs, upstreams_by_id)
        except Exception as e:
            print(f"radicalize: sync failed for downstream {downstream_id}: {e}", file=sys.stderr)
            traceback.print_exc()


def run_forever(data_dir: Path) -> None:
    paths.ensure_layout(data_dir)
    settings = load_radicale_settings(data_dir)
    last_run: dict[str, float] = {}
    print(f"radicalize: data_dir={data_dir} run loop (poll every 5s)")
    while True:
        try:
            upstreams_by_id, downstreams_by_id, pair_file = _load_world(data_dir)
        except Exception as e:
            print(f"radicalize: failed to load config: {e}", file=sys.stderr)
            time.sleep(5)
            continue

        grouped = _group_pairs_by_downstream(pair_file.pairs)
        now = time.monotonic()
        for downstream_id, pairs in grouped.items():
            downstream = downstreams_by_id.get(downstream_id)
            if downstream is None:
                continue
            interval = downstream.sync_interval_seconds or settings.sync_interval_seconds
            prev = last_run.get(downstream_id, 0.0)
            if prev != 0.0 and now - prev < interval:
                continue
            try:
                sync_downstream(data_dir, settings, downstream, pairs, upstreams_by_id)
            except Exception as e:
                print(
                    f"radicalize: sync failed for downstream {downstream_id}: {e}",
                    file=sys.stderr,
                )
                traceback.print_exc()
            last_run[downstream_id] = time.monotonic()

        time.sleep(5)
