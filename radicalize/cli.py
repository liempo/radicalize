import enum
import errno
import shutil
import sys
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


class SourceChoice(str, enum.Enum):
    google = "google"
    ics = "ics"


class MethodChoice(str, enum.Enum):
    replace = "replace"
    update = "update"


DataDirOption = Annotated[
    Optional[Path],
    typer.Option(
        "--data-dir",
        "-d",
        help="Data root (default: ~/.calendar/radicalize or RADICALIZE_DATA)",
    ),
]


@app.callback()
def _app_root(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = data_dir


def _register_group_data_dir_callback(group: typer.Typer) -> None:
    """Let ``--data-dir`` appear after the group name (e.g. ``pair --data-dir PATH list``)."""

    @group.callback()
    def _group_data_dir(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
        ctx.ensure_object(dict)
        inherited: Optional[Path] = None
        parent = ctx.parent
        if parent is not None:
            pobj = getattr(parent, "obj", None)
            if isinstance(pobj, dict):
                inherited = pobj.get("data_dir")
        ctx.obj["data_dir"] = data_dir if data_dir is not None else inherited


_register_group_data_dir_callback(upstream_app)
_register_group_data_dir_callback(downstream_app)
_register_group_data_dir_callback(pair_app)


def _resolve_data_dir_ctx(ctx: typer.Context, explicit: Optional[Path]) -> Path:
    """Prefer per-command --data-dir, then any parent group/root ``--data-dir``, then env/default."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    walk: Optional[typer.Context] = ctx
    while walk is not None:
        obj = getattr(walk, "obj", None)
        if isinstance(obj, dict):
            d = obj.get("data_dir")
            if d is not None:
                return Path(d).expanduser().resolve()
        walk = walk.parent
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


def _is_skippable_deletion_error(exc: BaseException) -> bool:
    """Bind mounts and read-only files often raise EBUSY / EROFS; do not abort reset."""
    if isinstance(exc, OSError):
        return exc.errno in (
            errno.EBUSY,
            errno.EROFS,
            errno.EACCES,
            errno.EPERM,
        )
    return False


def _unlink_best_effort(path: Path) -> None:
    try:
        path.unlink()
    except OSError as e:
        if _is_skippable_deletion_error(e):
            typer.echo(f"radicalize: skipping {path} ({e.strerror})", err=True)
            return
        raise


def _rmtree_best_effort(path: Path) -> None:
    if sys.version_info >= (3, 12):

        def onexc(func: object, p: str, exc: BaseException) -> None:
            _ = func
            if _is_skippable_deletion_error(exc):
                typer.echo(f"radicalize: skipping {p} ({exc})", err=True)
                return
            raise exc

        shutil.rmtree(path, onexc=onexc)
    else:

        def onerror(func: object, p: str, exc_info) -> None:
            _ = func
            _, exc, _tb = exc_info  # (type, value, traceback)
            if _is_skippable_deletion_error(exc):
                typer.echo(f"radicalize: skipping {p} ({exc})", err=True)
                return
            raise exc

        shutil.rmtree(path, onerror=onerror)


def _reset_remove_child(child: Path, root: Path) -> None:
    """Remove one top-level entry under DATA_DIR, leaving ignored bind mounts intact."""
    ignore_dotenv = paths.data_dotenv_path(root)
    ignore_oauth = paths.google_oauth_json_bind_path(root)
    if child.resolve() == ignore_dotenv.resolve():
        typer.echo(f"radicalize: leaving {child} in place (ignored path)", err=True)
        return
    if child.resolve() == ignore_oauth.resolve():
        typer.echo(f"radicalize: leaving {child} in place (ignored path)", err=True)
        return
    if child.is_dir() and not child.is_symlink() and child.name == "google":
        for sub in list(child.iterdir()):
            if sub.resolve() == ignore_oauth.resolve():
                typer.echo(f"radicalize: leaving {sub} in place (ignored path)", err=True)
                continue
            if sub.is_dir() and not sub.is_symlink():
                _rmtree_best_effort(sub)
            else:
                _unlink_best_effort(sub)
        try:
            child.rmdir()
        except OSError:
            pass
        return
    if child.is_dir() and not child.is_symlink():
        _rmtree_best_effort(child)
    else:
        _unlink_best_effort(child)


@app.command("init")
def cmd_init(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Create the data directory layout (idempotent)."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _do_init(root)
    typer.echo(f"radicalize: initialized {root}")
    typer.echo(
        "Next: copy .env.example to .env, then run "
        "`radicalize upstream add <id>` and `radicalize downstream add <id>`."
    )


@app.command("reset")
def cmd_reset(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete almost everything in DATA_DIR and re-run init.

    Leaves ``.env`` and ``google/oauth.json`` in place (ignored bind-mount paths).
    """
    root = _resolve_data_dir_ctx(ctx, data_dir)
    if not yes:
        typer.confirm(
            "This will permanently delete everything under "
            f"{root} except ignored bind mounts (.env, google/oauth.json). "
            "OAuth tokens under tokens/ will be removed. Continue?",
            abort=True,
        )
    if root.exists():
        for child in root.iterdir():
            _reset_remove_child(child, root)
    _do_init(root)
    typer.echo(f"radicalize: reset and re-initialized {root}")


# Upstream subcommands

def _build_upstream_non_interactive(
    upstream_id: str,
    *,
    source: SourceChoice,
    name: Optional[str],
    google_calendar_id: Optional[str],
    ics_url: Optional[str],
    prefill: Optional[Upstream] = None,
) -> Upstream:
    """Build an Upstream from explicit flags. Falls back to prefill values when omitted."""
    if source is SourceChoice.google:
        gcal = (
            google_calendar_id
            if google_calendar_id is not None
            else (prefill.google_calendar_id if isinstance(prefill, GoogleUpstream) else "primary")
        )
        return GoogleUpstream(id=upstream_id, name=name, google_calendar_id=gcal)
    url = (
        ics_url
        if ics_url is not None
        else (prefill.external_ics_url if isinstance(prefill, IcsUpstream) else None)
    )
    if not url:
        raise typer.BadParameter("--ics-url is required for source 'ics'")
    return IcsUpstream(id=upstream_id, name=name, external_ics_url=url)


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


def _maybe_run_google_oauth(
    data_dir: Path,
    upstream: Upstream,
    *,
    interactive: bool,
    skip: bool,
) -> None:
    """In interactive mode, prompt; in non-interactive mode, only run when explicitly requested."""
    if not isinstance(upstream, GoogleUpstream):
        return
    if skip:
        typer.echo(
            "Skipped Google OAuth. Re-run later with: "
            f"radicalize upstream edit {upstream.id}"
        )
        return
    if interactive and not typer.confirm("Run Google OAuth now?", default=True):
        typer.echo(
            "Skipped Google OAuth. Re-run later with: "
            f"radicalize upstream edit {upstream.id}"
        )
        return
    if not interactive:
        return
    try:
        from radicalize.sync.google import run_google_oauth

        token_path = run_google_oauth(data_dir, upstream)
        typer.echo(f"Google token saved to {token_path}")
    except Exception as e:
        typer.echo(f"Google OAuth failed: {e}", err=True)
        raise typer.Exit(code=1) from e


SourceOption = Annotated[
    Optional[SourceChoice],
    typer.Option("--source", "-s", help="Upstream source. Enables non-interactive mode."),
]
NameOption = Annotated[Optional[str], typer.Option("--name", help="Display name (optional).")]
GoogleCalendarIdOption = Annotated[
    Optional[str],
    typer.Option("--google-calendar-id", help="Google calendar id (default: 'primary')."),
]
IcsUrlOption = Annotated[
    Optional[str],
    typer.Option("--ics-url", help="ICS or webcal URL (required when --source ics)."),
]
NoOauthOption = Annotated[
    bool,
    typer.Option("--no-oauth", help="Skip the Google OAuth flow even in interactive mode."),
]


@upstream_app.command("add")
def cmd_upstream_add(
    ctx: typer.Context,
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    source: SourceOption = None,
    name: NameOption = None,
    google_calendar_id: GoogleCalendarIdOption = None,
    ics_url: IcsUrlOption = None,
    no_oauth: NoOauthOption = False,
    data_dir: DataDirOption = None,
) -> None:
    """Add a new upstream definition. Interactive unless --source is given."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    if paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} already exists. Use `upstream edit` instead.", err=True)
        raise typer.Exit(code=1)
    if source is None:
        upstream = _prompt_upstream(upstream_id)
        interactive = True
    else:
        upstream = _build_upstream_non_interactive(
            upstream_id,
            source=source,
            name=name,
            google_calendar_id=google_calendar_id,
            ics_url=ics_url,
        )
        interactive = False
    out = save_upstream(root, upstream)
    typer.echo(f"Wrote {out}")
    _maybe_run_google_oauth(root, upstream, interactive=interactive, skip=no_oauth)


@upstream_app.command("edit")
def cmd_upstream_edit(
    ctx: typer.Context,
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    source: SourceOption = None,
    name: NameOption = None,
    google_calendar_id: GoogleCalendarIdOption = None,
    ics_url: IcsUrlOption = None,
    no_oauth: NoOauthOption = False,
    data_dir: DataDirOption = None,
) -> None:
    """Update an existing upstream. Interactive unless --source is given."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    if not paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} not found. Use `upstream add` first.", err=True)
        raise typer.Exit(code=1)
    existing = load_upstream(root, upstream_id)
    if source is None and name is None and google_calendar_id is None and ics_url is None:
        upstream = _prompt_upstream(upstream_id, prefill=existing)
        interactive = True
    else:
        effective_source = source or (
            SourceChoice.google if isinstance(existing, GoogleUpstream) else SourceChoice.ics
        )
        upstream = _build_upstream_non_interactive(
            upstream_id,
            source=effective_source,
            name=name if name is not None else existing.name,
            google_calendar_id=google_calendar_id,
            ics_url=ics_url,
            prefill=existing,
        )
        interactive = False
    out = save_upstream(root, upstream)
    typer.echo(f"Wrote {out}")
    _maybe_run_google_oauth(root, upstream, interactive=interactive, skip=no_oauth)


@upstream_app.command("remove")
def cmd_upstream_remove(
    ctx: typer.Context,
    upstream_id: Annotated[str, typer.Argument(help="Upstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove an upstream, its OAuth token, and any pair entries referencing it."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
def cmd_upstream_list(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """List configured upstreams."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
    try:
        sync_interval_seconds = int(interval_str) if interval_str else None
    except ValueError as e:
        raise typer.BadParameter("sync interval must be an integer") from e

    return Downstream(
        id=downstream_id,
        name=name,
        href=href,
        sync_interval_seconds=sync_interval_seconds,
    )


HrefOption = Annotated[
    Optional[str],
    typer.Option("--href", help="Radicale collection href (defaults to id)."),
]
SyncIntervalOption = Annotated[
    Optional[int],
    typer.Option(
        "--sync-interval-seconds",
        min=1,
        help="Per-downstream sync interval in seconds (omit for global default).",
    ),
]


def _is_downstream_non_interactive(*flags: Optional[object]) -> bool:
    return any(flag is not None for flag in flags)


@downstream_app.command("add")
def cmd_downstream_add(
    ctx: typer.Context,
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    name: NameOption = None,
    href: HrefOption = None,
    sync_interval_seconds: SyncIntervalOption = None,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Skip prompts; use only flag values / defaults."),
    ] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Add a new downstream Radicale collection."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    if paths.downstream_path(root, downstream_id).exists():
        typer.echo(
            f"Downstream {downstream_id!r} already exists. Use `downstream edit` instead.",
            err=True,
        )
        raise typer.Exit(code=1)
    if non_interactive or _is_downstream_non_interactive(name, href, sync_interval_seconds):
        downstream = Downstream(
            id=downstream_id,
            name=name,
            href=href,
            sync_interval_seconds=sync_interval_seconds,
        )
    else:
        downstream = _prompt_downstream(downstream_id)
    out = save_downstream(root, downstream)
    typer.echo(f"Wrote {out}")


@downstream_app.command("edit")
def cmd_downstream_edit(
    ctx: typer.Context,
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    name: NameOption = None,
    href: HrefOption = None,
    sync_interval_seconds: SyncIntervalOption = None,
    data_dir: DataDirOption = None,
) -> None:
    """Update an existing downstream. Interactive unless any field flag is supplied."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    if not paths.downstream_path(root, downstream_id).exists():
        typer.echo(
            f"Downstream {downstream_id!r} not found. Use `downstream add` first.",
            err=True,
        )
        raise typer.Exit(code=1)
    existing = load_downstream(root, downstream_id)
    if _is_downstream_non_interactive(name, href, sync_interval_seconds):
        downstream = Downstream(
            id=downstream_id,
            name=name if name is not None else existing.name,
            href=href if href is not None else existing.href,
            sync_interval_seconds=(
                sync_interval_seconds
                if sync_interval_seconds is not None
                else existing.sync_interval_seconds
            ),
        )
    else:
        downstream = _prompt_downstream(downstream_id, prefill=existing)
    out = save_downstream(root, downstream)
    typer.echo(f"Wrote {out}")


@downstream_app.command("remove")
def cmd_downstream_remove(
    ctx: typer.Context,
    downstream_id: Annotated[str, typer.Argument(help="Downstream id (slug)")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove a downstream and any pair entries referencing it."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
def cmd_downstream_list(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """List configured downstreams."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
    ctx: typer.Context,
    upstream_id: Annotated[str, typer.Option("--upstream", help="Upstream id")],
    downstream_id: Annotated[str, typer.Option("--downstream", help="Downstream id")],
    method: Annotated[
        MethodChoice,
        typer.Option("--method", help="Merge method", case_sensitive=False),
    ] = MethodChoice.update,
    data_dir: DataDirOption = None,
) -> None:
    """Append a new upstream→downstream pair."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    if not paths.upstream_path(root, upstream_id).exists():
        typer.echo(f"Upstream {upstream_id!r} not found. Add it first.", err=True)
        raise typer.Exit(code=1)
    if not paths.downstream_path(root, downstream_id).exists():
        typer.echo(f"Downstream {downstream_id!r} not found. Add it first.", err=True)
        raise typer.Exit(code=1)
    pair_file = load_pair_file(root)
    pair_file.pairs.append(
        Pair(upstream_id=upstream_id, downstream_id=downstream_id, method=method.value)  # type: ignore[arg-type]
    )
    save_pair_file(root, pair_file)
    typer.echo(f"Added pair {upstream_id} -> {downstream_id} ({method.value})")


@pair_app.command("remove")
def cmd_pair_remove(
    ctx: typer.Context,
    upstream_id: Annotated[str, typer.Option("--upstream", help="Upstream id")],
    downstream_id: Annotated[str, typer.Option("--downstream", help="Downstream id")],
    data_dir: DataDirOption = None,
) -> None:
    """Remove a pair (matched by upstream + downstream ids; removes all matches)."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
def cmd_pair_list(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """List configured pairs (in order)."""
    root = _resolve_data_dir_ctx(ctx, data_dir)
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
def cmd_sync(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Run one sync pass for all configured pairs."""
    from radicalize.runner import sync_all

    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    try:
        sync_all(root)
    except Exception as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


@app.command("run")
def cmd_run(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Run periodic sync loop (reads .env from data dir)."""
    from radicalize.runner import run_forever

    root = _resolve_data_dir_ctx(ctx, data_dir)
    _ensure_initialized(root)
    try:
        run_forever(root)
    except KeyboardInterrupt:
        typer.echo("Stopped.")
        raise typer.Exit(0) from None


if __name__ == "__main__":
    app()
