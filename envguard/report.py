"""Human-readable and JSON reporters for scan results."""

from __future__ import annotations

import json

from .analyzer import ScanResult

_ICONS = {"error": "[X]", "warning": "[!]", "info": "[i]"}


def render_text(result: ScanResult) -> str:
    lines: list[str] = []
    lines.append(f"EnvGuard scan of {result.project_dir}")
    lines.append(
        f"  {result.files_scanned} source files, {result.refs_found} env references,"
        f" {result.keys_declared} declared keys"
        f" ({', '.join(result.env_files) or 'no env files found'})"
    )
    lines.append("")
    if not result.findings:
        lines.append("No drift detected. Environment files are in sync with code.")
        return "\n".join(lines)

    order = {"error": 0, "warning": 1, "info": 2}
    for f in sorted(result.findings, key=lambda f: (order[f.severity], f.kind, f.key)):
        lines.append(f"{_ICONS[f.severity]} {f.kind:<8} {f.key}")
        lines.append(f"    {f.detail}")
        for loc in f.locations:
            lines.append(f"      at {loc}")
    counts = {s: sum(1 for f in result.findings if f.severity == s)
              for s in ("error", "warning", "info")}
    lines.append("")
    lines.append(
        f"Summary: {counts['error']} error(s), {counts['warning']} warning(s),"
        f" {counts['info']} info"
    )
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    return json.dumps(
        {
            "project_dir": result.project_dir,
            "files_scanned": result.files_scanned,
            "refs_found": result.refs_found,
            "keys_declared": result.keys_declared,
            "env_files": list(result.env_files),
            "findings": [
                {
                    "kind": f.kind,
                    "severity": f.severity,
                    "key": f.key,
                    "detail": f.detail,
                    "locations": list(f.locations),
                }
                for f in result.findings
            ],
        },
        indent=2,
    )
