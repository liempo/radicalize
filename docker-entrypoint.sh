#!/usr/bin/env sh
set -e

DATA_DIR="${RADICALIZE_DATA:-/data/calendar}"

if [ "$(id -u)" = "0" ] && [ -n "${RADICALIZED_UID}" ] && [ -n "${RADICALIZED_GID}" ]; then
    mkdir -p "$DATA_DIR"
    # Match ownership to RADICALIZED_UID/GID so the non-root sync process can write.
    # Skip root .env (often a read-only secret bind-mount). Read-only bind mounts under
    # DATA_DIR must not abort startup. Use POSIX find -exec (no bash read -d '').
    find "$DATA_DIR" -mindepth 1 \
        ! -path "$DATA_DIR/.env" \
        ! -path "$DATA_DIR/google/oauth.json" \
        -exec chown -h "${RADICALIZED_UID}:${RADICALIZED_GID}" {} \; \
        2>/dev/null || true
    exec gosu "${RADICALIZED_UID}:${RADICALIZED_GID}" radicalize "$@"
fi

exec radicalize "$@"
