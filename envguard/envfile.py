"""Parser for dotenv-style files.

Supports: comments, blank lines, `export KEY=...` prefixes, single/double
quoted values, and inline comments after unquoted values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LINE_RE = re.compile(
    r"""^\s*
        (?:export\s+)?
        (?P<key>[A-Za-z_][A-Za-z0-9_]*)
        \s*=\s*
        (?P<value>.*)$""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class EnvEntry:
    key: str
    value: str
    line: int


def parse_env_file(path: Path) -> dict[str, EnvEntry]:
    """Return {key: EnvEntry}. Later duplicates override earlier ones,
    matching dotenv runtime semantics."""
    entries: dict[str, EnvEntry] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        value = m.group("value").strip()
        if value[:1] in ("'", '"') and len(value) >= 2 and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # strip inline comment on unquoted values: KEY=foo  # comment
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        entries[m.group("key")] = EnvEntry(m.group("key"), value, lineno)
    return entries
