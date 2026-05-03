# radicalize

Radicale supervisor that syncs upstream calendars (Google, ICS) into Radicale collections, configured as a directed graph of `upstream → downstream` pairs with per-pair merge semantics.

## Concepts

- **Upstream** — an external calendar source: a Google calendar (OAuth) or an ICS / webcal URL.
- **Downstream** — a Radicale collection (`/{username}/{href}`) that receives merged events.
- **Pair** — an ordered edge `(upstream → downstream, method)` written to `pair.json`.
- **Method**:
  - `replace`: drop everything previously written to the downstream by this upstream (tracked via the `X-RADICALIZE-UPSTREAM-ID` property), then insert the upstream's current events. Other upstreams' events on the same downstream are preserved.
  - `update`: match upstream events to existing downstream events by `UID`. Existing matches are replaced; new ones are appended. Untouched events stay put.

For each downstream the supervisor reads the current Radicale state once, applies every pair targeting that downstream in `pair.json` order, and writes back a single PUT.

## Data layout (`DATA_DIR`)

Default `~/.calendar/radicalize` (override with `RADICALIZE_DATA`).

```
DATA_DIR/
  .radicalize                # marker file written by `init`
  .env / .env.example
  upstream/<id>.json         # google or ics upstream definitions
  downstream/<id>.json       # Radicale collection definitions
  pair.json                  # ordered list of pairs
  tokens/<upstream-id>.json  # Google OAuth tokens
  credentials/google-oauth-client.json
  google/oauth.json          # optional host bind-mount (ignored by reset / Docker chown)
```

Every command except `init` and `reset` auto-runs `init` if `DATA_DIR` is not yet initialized.

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `RADICALE_BASE_URL` | yes | e.g. `http://radicale:5232` (no trailing slash) |
| `RADICALE_USERNAME` | yes | Radicale HTTP Basic user |
| `RADICALE_PASSWORD` | yes | Radicale HTTP Basic password |
| `SYNC_INTERVAL_SECONDS` | no | Default poll interval (default `1800`) |
| `RADICALIZE_DATA` | no | Override DATA_DIR (default `~/.calendar/radicalize`; container default `/data/calendar`) |
| `OAUTH_PORT` | no | Local port for Google OAuth callback (default `8090`) |
| `RADICALIZED_UID` / `RADICALIZED_GID` | docker | uid/gid the sync container runs as after `chown` |
| `RADICALIZE_DATA_HOST` | docker | host path mounted into `/data/calendar` |

Values can also live in `DATA_DIR/.env` (loaded via `python-dotenv`).

## Docker (primary workflow)

The repo `docker-compose.yml` runs Radicale plus a `radicalize` service (and optional `chronos-mcp`). Ensure `DATA_DIR/.env` contains `RADICALE_*` credentials (or mount it read-only from your Radicale env file, as in the sample compose).

The shared `mcp-net` network is declared **`external: true`**. Create it once if it does not exist yet:

```bash
docker network create mcp-net
```

```bash
docker compose up -d --build
```

Then configure using one-off commands against the `radicalize` service:

```bash
docker compose run --rm radicalize init
docker compose run --rm radicalize downstream add merged --non-interactive
docker compose run --rm radicalize upstream add holidays --source ics --ics-url 'https://…/h.ics'
docker compose run --rm -p 8090:8090 radicalize upstream add work-google   # Google OAuth needs a published port
docker compose run --rm radicalize pair add --upstream holidays --downstream merged --method update
docker compose run --rm radicalize pair add --upstream work-google --downstream merged --method replace
```

The default service command is `run` (periodic sync loop); `RADICALIZE_DATA` points at `/data/calendar`. Logs: `docker compose logs -f radicalize`.

The entrypoint adjusts ownership under the data directory so the non-root `radicalize` process can write. Root `.env` uses POSIX-safe `chown`; **`google/oauth.json` is excluded entirely** (typical read-only Google OAuth client bind-mount). `radicalize reset` also leaves that file in place.

### Google OAuth in Docker

The Google flow runs a temporary local web server on `OAUTH_PORT` (default `8090`). Publish that port for the one-shot upstream wizard so the redirect resolves:

```bash
docker compose run --rm -p 8090:8090 radicalize upstream add my-google
```

A Desktop OAuth client JSON must be present at `DATA_DIR/credentials/google-oauth-client.json` before running the wizard.

## CLI

```bash
radicalize init
radicalize reset --yes                 # wipe DATA_DIR; skips undeletable paths (e.g. busy bind-mounted .env)

# Interactive wizards (no flags):
radicalize upstream add <id>
radicalize upstream edit <id>
radicalize downstream add <id>
radicalize downstream edit <id>

# Non-interactive (any flag enables non-interactive mode):
radicalize upstream add <id> --source google  --google-calendar-id primary [--name ...] [--no-oauth]
radicalize upstream add <id> --source ics     --ics-url https://example/h.ics [--name ...]
radicalize downstream add <id> [--name ...] [--href ...] [--sync-interval-seconds N] [--non-interactive]

radicalize upstream remove <id>        # also deletes token + strips matching pairs
radicalize upstream list
radicalize downstream remove <id>      # strips matching pairs
radicalize downstream list

radicalize pair add --upstream <u> --downstream <d> [--method update|replace]
radicalize pair remove --upstream <u> --downstream <d>
radicalize pair list

radicalize sync                        # one pass over all pairs
radicalize run                         # periodic loop
```

`--data-dir` (alias `-d`) may be placed before the subcommand (applies to the whole invocation) or on a specific command. It defaults to `RADICALIZE_DATA` or `~/.calendar/radicalize`. In Docker, `RADICALIZE_DATA` is set instead of passing `--data-dir`.

**Exit codes**: `0` success, `1` runtime error (missing entity, OAuth failure, sync failure), `2` usage error (invalid flag/value).

## Local install

```bash
pip install -e ".[dev]"
radicalize init
pytest
```

Requires Python 3.9+.
