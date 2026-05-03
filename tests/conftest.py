"""Pytest hooks and shared test setup."""

import os

# Typer reads these when `typer.rich_utils` is first imported (via `radicalize.cli`).
# GitHub Actions sets GITHUB_ACTIONS=1, which makes Typer force a TTY for Rich; inside
# Click's CliRunner that yields empty/truncated help. Constrain width and relax
# force_terminal before any test module imports the CLI.
os.environ.setdefault("TERMINAL_WIDTH", "120")
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")
