"""Project-level configuration loaded from `.envguardrc` (JSON) in the
scanned project's root.

Example .envguardrc:
{
  "ignore_keys": ["SENTRY_DSN", "FEATURE_*"],
  "skip_dirs": ["fixtures", "vendor"],
  "extra_patterns": ["config\\.get\\(\\s*['\"](?P<key>[A-Z_][A-Z0-9_]*)['\"]"]
}

- ignore_keys: keys (or glob patterns via fnmatch, e.g. "VITE_*") that are
  never reported as findings.
- skip_dirs: directory names to skip in addition to the built-in list.
- extra_patterns: extra regexes for custom env accessors; each must contain
  a named group `key`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

RC_NAME = ".envguardrc"


@dataclass(frozen=True)
class Config:
    ignore_keys: tuple[str, ...] = ()
    skip_dirs: frozenset[str] = frozenset()
    extra_patterns: tuple[re.Pattern, ...] = ()

    def is_ignored(self, key: str) -> bool:
        return any(fnmatchcase(key, pat) for pat in self.ignore_keys)


class ConfigError(ValueError):
    """Raised when .envguardrc is malformed."""


def load_config(root: Path) -> Config:
    rc = root / RC_NAME
    if not rc.is_file():
        return Config()
    try:
        data = json.loads(rc.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{RC_NAME} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{RC_NAME} must contain a JSON object")

    def str_list(name: str) -> list[str]:
        value = data.get(name, [])
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise ConfigError(f"{RC_NAME}: '{name}' must be a list of strings")
        return value

    patterns = []
    for raw in str_list("extra_patterns"):
        try:
            pat = re.compile(raw)
        except re.error as e:
            raise ConfigError(f"{RC_NAME}: bad regex {raw!r}: {e}") from e
        if "key" not in pat.groupindex:
            raise ConfigError(
                f"{RC_NAME}: pattern {raw!r} needs a named group (?P<key>...)")
        patterns.append(pat)

    unknown = set(data) - {"ignore_keys", "skip_dirs", "extra_patterns"}
    if unknown:
        raise ConfigError(f"{RC_NAME}: unknown option(s): {', '.join(sorted(unknown))}")

    return Config(
        ignore_keys=tuple(str_list("ignore_keys")),
        skip_dirs=frozenset(str_list("skip_dirs")),
        extra_patterns=tuple(patterns),
    )
