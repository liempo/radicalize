#!/usr/bin/env sh
set -e

DATA_DIR="${RADICALIZE_DATA:-/data/calendar}"

if [ "$(id -u)" = "0" ] && [ -n "${RADICALIZED_UID}" ] && [ -n "${RADICALIZED_GID}" ]; then
    mkdir -p "$DATA_DIR"
    # Match ownership to RADICALIZED_UID/GID so the non-root sync process can write.
    # Skip root .env (often a read-only secret bind-mount). Read-only bind mounts under
    # DATA_DIR (e.g. google/oauth.json) must not abort startup: chown each path, ignore failures.
    find "$DATA_DIR" -mindepth 1 ! -path "$DATA_DIR/.env" -print0 |
        while IFS= read -r -d '' p; do
            chown -h "${RADICALIZED_UID}:${RADICALIZED_GID}" "$p" 2>/dev/null || true
        done
    exec gosu "${RADICALIZED_UID}:${RADICALIZED_GID}" radicalize "$@"
fi

exec radicalize "$@"
