"""Polyglot source scanner: finds environment-variable references.

Covered patterns
  JS/TS:  process.env.KEY            process.env["KEY"]
          import.meta.env.KEY        const { A, B } = process.env
  Python: os.environ["KEY"]          os.environ.get("KEY", ...)
          os.getenv("KEY", ...)      environ["KEY"] (from-import style)
  Go:     os.Getenv("KEY")           os.LookupEnv("KEY")
  Ruby:   ENV["KEY"]                 ENV.fetch("KEY", ...)
  PHP:    getenv("KEY")              $_ENV["KEY"]    $_SERVER["KEY"]

Projects can add custom accessor regexes via `.envguardrc` extra_patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import Config

SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py",
                     ".vue", ".svelte", ".go", ".rb", ".php"}

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".nuxt", "coverage", ".tox", ".mypy_cache", ".pytest_cache",
}

_KEY = r"[A-Za-z_][A-Za-z0-9_]*"

_PATTERNS: list[re.Pattern] = [
    re.compile(rf"process\.env\.(?P<key>{_KEY})"),
    re.compile(rf"process\.env\[\s*['\"](?P<key>{_KEY})['\"]\s*\]"),
    re.compile(rf"import\.meta\.env\.(?P<key>{_KEY})"),
    re.compile(rf"os\.environ\[\s*['\"](?P<key>{_KEY})['\"]\s*\]"),
    re.compile(rf"(?:os\.)?environ\.get\(\s*['\"](?P<key>{_KEY})['\"]"),
    re.compile(rf"os\.getenv\(\s*['\"](?P<key>{_KEY})['\"]"),
    # Go
    re.compile(rf"os\.(?:Getenv|LookupEnv)\(\s*\"(?P<key>{_KEY})\""),
    # Ruby
    re.compile(rf"ENV\[\s*['\"](?P<key>{_KEY})['\"]\s*\]"),
    re.compile(rf"ENV\.fetch\(\s*['\"](?P<key>{_KEY})['\"]"),
    # PHP — bare getenv(); lookbehind keeps it from double-matching os.getenv
    re.compile(rf"(?<![\w.])getenv\(\s*['\"](?P<key>{_KEY})['\"]"),
    re.compile(rf"\$_(?:ENV|SERVER)\[\s*['\"](?P<key>{_KEY})['\"]\s*\]"),
]

# const { A, B: alias, C = "default" } = process.env  (may span lines)
_DESTRUCTURE_RE = re.compile(
    r"(?:const|let|var)\s*\{(?P<body>[^}]*)\}\s*=\s*process\.env"
)
# env keys appear at the start of the body or right after a comma; anything
# after ':' is a local alias and anything after '=' is a default value.
_DESTRUCTURE_KEY_RE = re.compile(rf"(?:^|,)\s*(?P<key>{_KEY})")

# Framework/runtime keys that are injected, not declared in .env files.
BUILTIN_KEYS = {"NODE_ENV", "PATH", "HOME", "PWD", "TZ", "CI", "PORT",
                "PYTHONPATH", "VIRTUAL_ENV", "MODE", "DEV", "PROD", "SSR",
                "BASE_URL"}


@dataclass(frozen=True)
class Reference:
    key: str
    file: str   # path relative to project root, posix-style
    line: int


def _iter_source_files(root: Path, skip_dirs: frozenset[str]) -> Iterator[Path]:
    skip = SKIP_DIRS | skip_dirs
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if path.is_file() and path.suffix in SOURCE_EXTENSIONS:
            yield path


def scan_file(path: Path, root: Path, config: Config = Config()) -> list[Reference]:
    refs: list[Reference] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return refs
    rel = path.relative_to(root).as_posix()
    patterns = list(_PATTERNS) + list(config.extra_patterns)
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in patterns:
            for m in pat.finditer(line):
                refs.append(Reference(m.group("key"), rel, lineno))
    # Destructuring may span multiple lines, so match against the full text
    # and recover the line number from the match offset.
    for m in _DESTRUCTURE_RE.finditer(text):
        lineno = text.count("\n", 0, m.start()) + 1
        for km in _DESTRUCTURE_KEY_RE.finditer(m.group("body")):
            refs.append(Reference(km.group("key"), rel, lineno))
    return refs


def scan_project(root: Path, config: Config = Config()) -> tuple[list[Reference], int]:
    """Return (references, files_scanned)."""
    refs: list[Reference] = []
    count = 0
    for f in _iter_source_files(root, config.skip_dirs):
        count += 1
        refs.extend(scan_file(f, root, config))
    return refs, count
