import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer

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
    Upstream,
)


app = typer.Typer(
    help="Radicalize — supervisor that syncs upstream calendars (Google, ICS) into Radicale.",
    no_args_is_help=True,
)
upstream_app = typer.Typer(help="Manage upstream calendar definitions.", no_args_is_help=True)
downstream_app = typer.Typer(help="Manage downstream Radicale collection definitions.", no_args_is_help=True)
pair_app = typer.Typer(help="Manage upstream→downstream pairings.", no_args_is_help=True)
app.add_typer(upstream_app, name="upstream")
app.add_typer(downstream_app, name="downstream")
app.add_typer(pair_app, name="pair")


DataDirOption = Annotated[
    Optional[Path],
    typer.Option("--data-dir", help="Data root (default: ~/.calendar/radicalize or RADICALIZE_DATA)"),
]


def _resolve_data_dir(data_dir: Optional[Path]) -> Path:
    if data_dir is not None:
        return data_dir.expanduser().resolve()
    return paths.default_data_dir()


def _ensure_initialized(data_dir: Path) -> None:
    """Make sure DATA_DIR exists and is initialized; auto-init on first run."""
    if paths.is_initialized(data_dir):
        return
    typer.echo(f"radicalize: initializing data dir {data_dir}")
    _do_init(data_dir)


def _write_env_example(data_dir: Path) -> None:
    example = data_dir / ".env.example"
    if example.exists():
        return
    example.write_text(
        "\n".join(
            [
                "RADICALE_BASE_URL=http://127.0.0.1:5232",
                "RADICALE_USERNAME=user",
                "RADICALE_PASSWORD=test",
                "SYNC_INTERVAL_SECONDS=1800",
                "# RADICALIZE_DATA=" + str(data_dir),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _do_init(data_dir: Path) -> None:
    paths.ensure_layout(data_dir)
    _write_env_example(data_dir)


@app.command("init")
def cmd_init(data_dir: DataDirOption = None) -> None:
    """Create the data directory layout (idempotent)."""
    root = _resolve_data_dir(data_dir)
    _do_init(root)
    typer.echo(f"radicalize: initialized {root}")
    typer.echo(
        "Next: copy .env.example to .env, then run "
        "`radicalize upstream add <id>` and `radicalize downstream add <id>`."
    )


@app.command("reset")
def cmd_reset(
    data_dir: DataDirOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete everything in DATA_DIR and re-run init."""
    root = _resolve_data_dir(data_dir)
    if not yes:
        typer.confirm(
            f"This will permanently delete all contents of {root} (including OAuth tokens). Continue?",
            abort=True,
        )
    if root.exists():
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    _do_init(root)
    typer.echo(f"radicalize: reset and re-initialized {root}")


# Upstream subcommands

def _prompt_upstream(upstream_id: str, prefill: Optional[Upstream] = None) -> Upstream:
    typer.echo("Choose upstream source:")
    typer.echo("  1) google")
    typer.echo("  2) ics")
    default_choice = 1
    if isinstance(prefill, IcsUpstream):
        default_choice = 2
    choice = typer.prompt("Choice", type=int, default=default_choice)

    name_default = prefill.name if (prefill and prefill.name) else ""
    name = typer.prompt("Display name (optional)", default=name_default, show_default=bool(name_default)).strip() or None

    if choice == 1:
        gcal_default = (
            prefill.google_calendar_id if isinstance(prefill, GoogleUpstream) else "primary"
        )
        google_calendar_id = typer.prompt("Google calendar id", default=gcal_default)
        return GoogleUpstream(id=upstream_id, name=name, google_calendar_id=google_calendar_id)
    if choice == 2:
        url_default = prefill.external_ics_url if isinstance(prefill, IcsUpstream) else ""
        external_ics_url = typer.prompt(
            "ICS / webcal URL",
            default=url_default,
            show_default=bool(url_default),
        )
        return IcsUpstream(id=upstream_id, name=name, external_ics_url=external_ics_url)
    raise typer.BadParameter("Invalid choice")


def _maybe_run_google_oauth(data_dir: Path, upstream: Upstream) -> None:
    if not isinstance(upstream, GoogleUpstream):
        return
    if not typer.confirm("Run Google OAuth now?", default=True):
        typer.echo(
            "Skipped. Re-run later with: "
            f"radicalize upstream edit {upstream.id}"
        )
        return
    try:
        from radicalize.sync.google import run_google_oauth

        token_path = run_google_oauth(data_dir, upstream)
        typer.echo(f"Google token saved to {token_path}")
    except Exception as e:
        typer.echo(f"Google OAuth failed: {e}", err=True)
        raise typer.Exit(code=1) from e


@upstream_app.command("add")
def cmd_upstream_add(
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Add a new upstream definition."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    if paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} already exists. Use `upstream edit` instead.", err=True)
        raise typer.Exit(code=1)
    upstream = _prompt_upstream(upstream_id)
    out = save_upstream(root, upstream)
    typer.echo(f"Wrote {out}")
    _maybe_run_google_oauth(root, upstream)


@upstream_app.command("edit")
def cmd_upstream_edit(
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Re-prompt the add wizard for an existing upstream."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    if not paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} not found. Use `upstream add` first.", err=True)
        raise typer.Exit(code=1)
    existing = load_upstream(root, upstream_id)
    upstream = _prompt_upstream(upstream_id, prefill=existing)
    out = save_upstream(root, upstream)
    typer.echo(f"Wrote {out}")
    _maybe_run_google_oauth(root, upstream)


@upstream_app.command("remove")
def cmd_upstream_remove(
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove an upstream, its OAuth token, and any pair entries referencing it."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    upstream_path = paths.upstream_path(root, upstream_id)
    if not upstream_path.exists():
        typer.echo(f"Upstream {upstream_id!r} not found.", err=True)
        raise typer.Exit(code=1)
    upstream_path.unlink()
    typer.echo(f"Removed {upstream_path}")

    token_path = paths.google_token_path(root, upstream_id)
    if token_path.exists():
        token_path.unlink()
        typer.echo(f"Removed token {token_path}")

    pair_file = load_pair_file(root)
    new_pair_file, removed = remove_pairs_referencing(pair_file, upstream_id=upstream_id)
    if removed:
        save_pair_file(root, new_pair_file)
        typer.echo(f"Removed {removed} pair entr{'y' if removed == 1 else 'ies'} referencing {upstream_id!r}")


@upstream_app.command("list")
def cmd_upstream_list(data_dir: DataDirOption = None) -> None:
    """List configured upstreams."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    upstreams = load_all_upstreams(root)
    if not upstreams:
        typer.echo("(no upstreams)")
        return
    for u in upstreams:
        typer.echo(f"{u.id}\t{u.source}\t{u.name or ''}")


# Downstream subcommands

def _prompt_downstream(downstream_id: str, prefill: Optional[Downstream] = None) -> Downstream:
    name_default = prefill.name if (prefill and prefill.name) else ""
    name = typer.prompt("Display name (optional)", default=name_default, show_default=bool(name_default)).strip() or None

    href_default = prefill.href if (prefill and prefill.href) else ""
    href = typer.prompt(
        "Radicale collection href (default: id)",
        default=href_default,
        show_default=bool(href_default),
    ).strip() or None

    interval_default = prefill.sync_interval_seconds if prefill else None
    interval_str = typer.prompt(
        "Per-downstream sync interval seconds (blank for global default)",
        default=str(interval_default) if interval_default else "",
        show_default=bool(interval_default),
    ).strip()
    sync_interval_seconds = int(interval_str) if interval_str else None

    return Downstream(
        id=downstream_id,
        name=name,
        href=href,
        sync_interval_seconds=sync_interval_seconds,
    )


@downstream_app.command("add")
def cmd_downstream_add(
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Add a new downstream Radicale collection."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    if paths.downstream_path(root, downstream_id).exists():
        typer.echo(
            f"Downstream {downstream_id!r} already exists. Use `downstream edit` instead.",
            err=True,
        )
        raise typer.Exit(code=1)
    downstream = _prompt_downstream(downstream_id)
    out = save_downstream(root, downstream)
    typer.echo(f"Wrote {out}")


@downstream_app.command("edit")
def cmd_downstream_edit(
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Re-prompt the add wizard for an existing downstream."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    if not paths.downstream_path(root, downstream_id).exists():
        typer.echo(
            f"Downstream {downstream_id!r} not found. Use `downstream add` first.",
            err=True,
        )
        raise typer.Exit(code=1)
    existing = load_downstream(root, downstream_id)
    downstream = _prompt_downstream(downstream_id, prefill=existing)
    out = save_downstream(root, downstream)
    typer.echo(f"Wrote {out}")


@downstream_app.command("remove")
def cmd_downstream_remove(
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove a downstream and any pair entries referencing it."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    downstream_path = paths.downstream_path(root, downstream_id)
    if not downstream_path.exists():
        typer.echo(f"Downstream {downstream_id!r} not found.", err=True)
        raise typer.Exit(code=1)
    downstream_path.unlink()
    typer.echo(f"Removed {downstream_path}")

    pair_file = load_pair_file(root)
    new_pair_file, removed = remove_pairs_referencing(pair_file, downstream_id=downstream_id)
    if removed:
        save_pair_file(root, new_pair_file)
        typer.echo(f"Removed {removed} pair entr{'y' if removed == 1 else 'ies'} referencing {downstream_id!r}")


@downstream_app.command("list")
def cmd_downstream_list(data_dir: DataDirOption = None) -> None:
    """List configured downstreams."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    downstreams = load_all_downstreams(root)
    if not downstreams:
        typer.echo("(no downstreams)")
        return
    for d in downstreams:
        href = d.href or d.id
        typer.echo(f"{d.id}\t{href}\t{d.name or ''}")


# Pair commands

@pair_app.command("add")
def cmd_pair_add(
    upstream_id: Annotated[str, typer.Option("--upstream", help="Upstream id")],
    downstream_id: Annotated[str, typer.Option("--downstream", help="Downstream id")],
    method: Annotated[str, typer.Option("--method", help="replace or update")] = "update",
    data_dir: DataDirOption = None,
) -> None:
    """Append a new upstream→downstream pair."""
    if method not in ("replace", "update"):
        typer.echo("--method must be 'replace' or 'update'", err=True)
        raise typer.Exit(code=2)
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    if not paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} not found. Add it first.", err=True)
        raise typer.Exit(code=1)
    if not paths.downstream_path(root, downstream_id).exists():
        typer.echo(f"Downstream {downstream_id!r} not found. Add it first.", err=True)
        raise typer.Exit(code=1)
    pair_file = load_pair_file(root)
    pair_file.pairs.append(
        Pair(upstream_id=upstream_id, downstream_id=downstream_id, method=method)  # type: ignore[arg-type]
    )
    save_pair_file(root, pair_file)
    typer.echo(f"Added pair {upstream_id} -> {downstream_id} ({method})")


@pair_app.command("remove")
def cmd_pair_remove(
    upstream_id: Annotated[str, typer.Option("--upstream", help="Upstream id")],
    downstream_id: Annotated[str, typer.Option("--downstream", help="Downstream id")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove a pair (matched by upstream + downstream ids; removes all matches)."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    pair_file = load_pair_file(root)
    keep = [
        p for p in pair_file.pairs
        if not (p.upstream_id == upstream_id and p.downstream_id == downstream_id)
    ]
    removed = len(pair_file.pairs) - len(keep)
    if removed == 0:
        typer.echo("No matching pair found.")
        return
    save_pair_file(root, PairFile(pairs=keep))
    typer.echo(f"Removed {removed} pair{'s' if removed != 1 else ''}")


@pair_app.command("list")
def cmd_pair_list(data_dir: DataDirOption = None) -> None:
    """List configured pairs (in order)."""
    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    pair_file = load_pair_file(root)
    upstreams = load_all_upstreams(root)
    downstreams = load_all_downstreams(root)
    errors = validate_pair_references(pair_file, upstreams, downstreams)
    for err in errors:
        typer.echo(f"warn: {err}", err=True)
    if not pair_file.pairs:
        typer.echo("(no pairs)")
        return
    for i, p in enumerate(pair_file.pairs):
        typer.echo(f"{i}\t{p.upstream_id} -> {p.downstream_id}\t{p.method}")


# Sync commands

@app.command("sync")
def cmd_sync(data_dir: DataDirOption = None) -> None:
    """Run one sync pass for all configured pairs."""
    from radicalize.runner import sync_all

    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    try:
        sync_all(root)
    except Exception as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


@app.command("run")
def cmd_run(data_dir: DataDirOption = None) -> None:
    """Run periodic sync loop (reads .env from data dir)."""
    from radicalize.runner import run_forever

    root = _resolve_data_dir(data_dir)
    _ensure_initialized(root)
    try:
        run_forever(root)
    except KeyboardInterrupt:
        typer.echo("Stopped.")
        raise typer.Exit(0) from None


if __name__ == "__main__":
    app()
