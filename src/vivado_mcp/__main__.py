from __future__ import annotations

import argparse
import sys

from vivado_mcp import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vivado-mcp",
        description="Vivado MCP Server",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")

    sub.add_parser("serve", help="Start the MCP server over stdio.")

    p_install = sub.add_parser(
        "install",
        help="Inject Vivado_init.tcl so Vivado GUI starts the localhost-only TCP bridge.",
    )
    p_install.add_argument("vivado_path", nargs="?", help="Optional Vivado executable path.")
    p_install.add_argument("--port", type=int, default=9999, help="Preferred TCP port.")
    p_install.add_argument(
        "--auth-token",
        default="",
        help="Optional auth token. If omitted, vivado-mcp reuses or generates one and stores it locally.",
    )
    p_install.add_argument(
        "--dev",
        action="store_true",
        help="Source the Tcl bridge directly from the working tree instead of installing a stable copy.",
    )

    p_uninstall = sub.add_parser(
        "uninstall",
        help="Remove vivado-mcp injection from Vivado_init.tcl.",
    )
    p_uninstall.add_argument("vivado_path", nargs="?", help="Optional Vivado executable path.")

    sub.add_parser("version", help="Show the version and exit.")

    args = parser.parse_args()

    if args.cmd in (None, "serve"):
        from vivado_mcp.server import mcp

        mcp.run(transport="stdio")
        return

    if args.cmd == "version":
        print(f"vivado-mcp {__version__}")
        return

    if args.cmd == "install":
        from vivado_mcp.install import install

        try:
            install(
                vivado_path=args.vivado_path,
                port=args.port,
                auth_token=args.auth_token or None,
                dev_mode=bool(args.dev),
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.cmd == "uninstall":
        from vivado_mcp.install import uninstall

        try:
            uninstall(vivado_path=args.vivado_path)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        return


if __name__ == "__main__":
    main()
