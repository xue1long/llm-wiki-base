"""`auth-token` CLI subcommand — manage the HTTP API bearer token (R1).

The token protects the HTTP management surface (/api/v1 write ops +
provider management) when the server binds a non-loopback host. Lifecycle:

- ``ruflo auth-token generate`` — create/rotate the token (prints once).
- ``ruflo auth-token show`` — print the current token (or "none").
- ``ruflo auth-token clear`` — remove the token (back to loopback-only).

Token storage: ``<config_dir>/auth.json`` (chmod 0600). The token is never
written to logs or the CLI history beyond the single generation print.
"""
from __future__ import annotations

import argparse

from ..server.auth import clear_token, generate_token, get_token, set_token


def cmd_auth_token_generate(args: argparse.Namespace) -> None:
    """Generate (or rotate) the bearer token and print it once."""
    token = generate_token()
    set_token(token)
    print(f"Bearer token saved to {args._auth_path}")
    print(f"Token: {token}")
    print("Add this header to API calls: Authorization: Bearer <token>")
    print("WARNING: store it securely — it grants full management access.")


def cmd_auth_token_show(args: argparse.Namespace) -> None:
    """Print the current token, or 'none' when auth is disabled."""
    token = get_token()
    if token is None:
        print("No bearer token configured (loopback-only mode).")
        return
    print(token)


def cmd_auth_token_clear(args: argparse.Namespace) -> None:
    """Remove the token; the API returns to loopback-only mode."""
    clear_token()
    print("Bearer token removed. The management API is now loopback-only; "
          "non-loopback binds will be refused.")


def add_auth_token_parser(subparsers) -> None:
    """Register the ``auth-token`` subcommand tree on ``subparsers``."""
    from ..project.paths import config_dir

    p = subparsers.add_parser(
        "auth-token",
        help="Manage the HTTP API bearer token (R1 management-surface auth)",
    )
    p_sub = p.add_subparsers(dest="auth_token_command", required=True)

    p_gen = p_sub.add_parser("generate", help="Generate or rotate the bearer token")
    p_gen.set_defaults(func=cmd_auth_token_generate)
    p_gen.set_defaults(_auth_path=str(config_dir() / "auth.json"))

    p_show = p_sub.add_parser("show", help="Print the current bearer token")
    p_show.set_defaults(func=cmd_auth_token_show)

    p_clear = p_sub.add_parser("clear", help="Remove the bearer token (loopback-only)")
    p_clear.set_defaults(func=cmd_auth_token_clear)
