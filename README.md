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

```bash
cp docker-data/.env.example docker-data/.env
# edit docker-data/.env: RADICALE_USERNAME / RADICALE_PASSWORD must match Radicale's auth

docker compose up -d --build
```

Then configure inside the volume using the `sync` service:

```bash
docker compose run --rm sync init
docker compose run --rm sync downstream add merged
docker compose run --rm sync upstream add holidays   # ics
docker compose run --rm -p 8090:8090 sync upstream add work-google   # google OAuth needs a published port
docker compose run --rm sync pair add --upstream holidays --downstream merged --method update
docker compose run --rm sync pair add --upstream work-google --downstream merged --method replace
```

The default Compose command (`run`) starts the periodic sync loop; the data directory is `/data/calendar` via `RADICALIZE_DATA`. Inspect with `docker compose logs -f sync`.

The entrypoint adjusts ownership under the data directory so the non-root `radicalize` process can write. Read-only bind mounts there (for example a secret at `google/oauth.json`) no longer stop the container: individual `chown` failures are ignored. Prefer keeping long-lived writable state under `RADICALIZE_DATA_HOST` and mounting secrets read-only only where the app reads them without needing write access.

### Google OAuth in Docker

The Google flow runs a temporary local web server on `OAUTH_PORT` (default `8090`). Publish that port for the one-shot upstream wizard so the redirect resolves:

```bash
docker compose run --rm -p 8090:8090 sync upstream add my-google
```

A Desktop OAuth client JSON must be present at `DATA_DIR/credentials/google-oauth-client.json` before running the wizard.

## CLI

```bash
radicalize init
radicalize reset --yes                 # delete DATA_DIR contents and re-init

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
