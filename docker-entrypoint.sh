#!/usr/bin/env sh
set -e

DATA_DIR="${RADICALIZE_DATA:-/data/calendar}"

if [ "$(id -u)" = "0" ] && [ -n "${RADICALIZED_UID}" ] && [ -n "${RADICALIZED_GID}" ]; then
    mkdir -p "$DATA_DIR"
    # Do not chown a root .env (often a read-only secret bind-mount).
    find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name ".env" -exec chown -R "${RADICALIZED_UID}:${RADICALIZED_GID}" {} +
    exec gosu "${RADICALIZED_UID}:${RADICALIZED_GID}" radicalize "$@"
fi

exec radicalize "$@"
