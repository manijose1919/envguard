"""EnvGuard command-line interface.

Usage:
  python -m envguard scan [DIR] [--json] [--ci] [--no-save]
  python -m envguard history [DIR] [--limit N]
  python -m envguard serve [DIR] [--port P]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import EXAMPLE_FILES, ScanResult, analyze
from .config import ConfigError
from .report import render_json, render_text
from .storage import Store

DB_NAME = ".envguard.db"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _resolve_dir(raw: str) -> Path:
    root = Path(raw).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    return root


def _apply_fix(root: Path, result: ScanResult) -> list[str]:
    """Append MISSING keys to the example env file (created if absent).
    Returns the keys that were added."""
    missing = sorted({f.key for f in result.findings if f.kind == "MISSING"})
    if not missing:
        return []
    existing = [n for n in result.env_files if n in EXAMPLE_FILES]
    target = root / (existing[0] if existing else ".env.example")
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n# Added by envguard --fix (fill in real values in your .env)\n"
    text += "".join(f"{key}=\n" for key in missing)
    target.write_text(text, encoding="utf-8")
    return missing


def cmd_scan(args: argparse.Namespace) -> int:
    root = _resolve_dir(args.dir)
    result = analyze(root)
    if args.fix:
        added = _apply_fix(root, result)
        if added:
            print(f"fixed: added {len(added)} key(s) to the example env file:"
                  f" {', '.join(added)}", file=sys.stderr)
            result = analyze(root)  # re-analyze so report and history reflect the fix
    if not args.no_save:
        with Store(root / DB_NAME) as store:
            store.save_scan(
                result.project_dir, result.files_scanned,
                result.refs_found, result.keys_declared, result.findings,
            )
    if args.json:
        print(render_json(result))
    else:
        print(render_text(result))
    if args.ci and result.has_errors:
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_history(args: argparse.Namespace) -> int:
    root = _resolve_dir(args.dir)
    db = root / DB_NAME
    if not db.is_file():
        print("No scan history yet. Run `envguard scan` first.", file=sys.stderr)
        return EXIT_USAGE
    with Store(db) as store:
        scans = store.list_scans(limit=args.limit)
    if not scans:
        print("Scan history is empty.")
        return EXIT_OK
    print(f"{'ID':>4}  {'When (UTC)':<20} {'Files':>6} {'Refs':>5} "
          f"{'Keys':>5} {'Err':>4} {'Warn':>5} {'Info':>5}")
    for s in scans:
        print(f"{s['id']:>4}  {s['created_at'][:19]:<20} {s['files_scanned']:>6} "
              f"{s['refs_found']:>5} {s['keys_declared']:>5} "
              f"{s['errors']:>4} {s['warnings']:>5} {s['infos']:>5}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import run_server  # deferred: keeps scan/history import-light
    root = _resolve_dir(args.dir)
    return run_server(root, args.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="envguard",
                                description="Environment variable drift detector")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scan", help="scan a project for env drift")
    sp.add_argument("dir", nargs="?", default=".", help="project root (default: .)")
    sp.add_argument("--json", action="store_true", help="emit JSON to stdout")
    sp.add_argument("--ci", action="store_true",
                    help="exit 1 if any error-severity findings exist")
    sp.add_argument("--no-save", action="store_true",
                    help="do not record this scan in history")
    sp.add_argument("--fix", action="store_true",
                    help="append MISSING keys to the example env file")
    sp.set_defaults(func=cmd_scan)

    hp = sub.add_parser("history", help="show past scans")
    hp.add_argument("dir", nargs="?", default=".")
    hp.add_argument("--limit", type=int, default=20)
    hp.set_defaults(func=cmd_history)

    vp = sub.add_parser("serve", help="launch the local dashboard")
    vp.add_argument("dir", nargs="?", default=".")
    vp.add_argument("--port", type=int, default=8765)
    vp.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
