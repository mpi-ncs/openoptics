#!/usr/bin/env python3
"""Render private Tofino configs from the public templates + secrets.local.toml.

The committed `config_4tor.toml` and `config_4tor_2link.toml` files ship with
placeholder hostnames / IPs / MACs so they can be safely open-sourced.  For
local runs, copy `secrets.local.toml.example` to `secrets.local.toml`, fill in
your real testbed values, and run this script.  It will write
`config_4tor.local.toml` and `config_4tor_2link.local.toml` alongside the
public templates.  Both `*.local.toml` and `secrets.local.toml` are gitignored.

Usage:
    cd openoptics/backends/tofino
    python3 apply_secrets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib  # Python >= 3.11
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found]


HERE = Path(__file__).resolve().parent
SECRETS_FILE = HERE / "secrets.local.toml"
TEMPLATES = ["config_4tor.toml", "config_4tor_2link.toml"]

# Maps token-as-it-appears-in-the-public-template -> secrets.local.toml key.
PLACEHOLDERS = {
    '"USER"':                 "USER",
    '"jumphost.example.com"': "JUMPHOST",
    '"OCS_SWITCH_IP"':        "OCS_SWITCH_IP",
    '"TOR_SWITCH_IP"':        "TOR_SWITCH_IP",
    '"tor-switch-1"':         "TOR_SWITCH_NAME",
    '"aa:bb:cc:dd:ee:01"':    "SERVER1_MAC",
    '"10.0.0.1"':             "SERVER1_HOST_IP",
    '"SERVER1_MGMT_IP"':      "SERVER1_MGMT_IP",
    '"aa:bb:cc:dd:ee:02"':    "SERVER2_MAC",
    '"10.0.0.2"':             "SERVER2_HOST_IP",
    '"SERVER2_MGMT_IP"':      "SERVER2_MGMT_IP",
}


def main() -> int:
    if not SECRETS_FILE.exists():
        example = SECRETS_FILE.with_suffix(".toml.example")
        print(
            f"error: {SECRETS_FILE.name} not found.\n"
            f"       Copy {example.name} to {SECRETS_FILE.name} and fill in "
            f"your testbed values.",
            file=sys.stderr,
        )
        return 1

    with SECRETS_FILE.open("rb") as f:
        secrets = tomllib.load(f)

    missing = [key for key in PLACEHOLDERS.values() if key not in secrets]
    if missing:
        print(
            f"error: {SECRETS_FILE.name} is missing required keys: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    for template_name in TEMPLATES:
        template_path = HERE / template_name
        if not template_path.exists():
            print(f"warn: {template_name} not found, skipping", file=sys.stderr)
            continue

        content = template_path.read_text()
        for token, key in PLACEHOLDERS.items():
            content = content.replace(token, f'"{secrets[key]}"')

        out_path = template_path.with_suffix(".local.toml")
        out_path.write_text(content)
        print(f"wrote {out_path.relative_to(HERE.parent.parent.parent)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
