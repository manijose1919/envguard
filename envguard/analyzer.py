"""Cross-references code references against env-file declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config
from .envfile import parse_env_file
from .scanner import BUILTIN_KEYS, Reference, scan_project
from .storage import Finding

ENV_FILE_CANDIDATES = (
    ".env", ".env.example", ".env.sample", ".env.template",
    ".env.local", ".env.development", ".env.production", ".env.test",
)

EXAMPLE_FILES = {".env.example", ".env.sample", ".env.template"}


@dataclass
class ScanResult:
    project_dir: str
    files_scanned: int
    references: list[Reference]
    env_files: dict[str, dict]          # filename -> {key: EnvEntry}
    findings: list[Finding] = field(default_factory=list)

    @property
    def refs_found(self) -> int:
        return len(self.references)

    @property
    def keys_declared(self) -> int:
        return len({k for entries in self.env_files.values() for k in entries})

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)


def _locations(refs: list[Reference], key: str, limit: int = 5) -> tuple[str, ...]:
    locs = [f"{r.file}:{r.line}" for r in refs if r.key == key]
    if len(locs) > limit:
        locs = locs[:limit] + [f"... and {len(locs) - limit} more"]
    return tuple(locs)


def analyze(root: Path) -> ScanResult:
    config = load_config(root)  # raises ConfigError on a malformed .envguardrc
    references, files_scanned = scan_project(root, config)
    env_files = {
        name: parse_env_file(root / name)
        for name in ENV_FILE_CANDIDATES
        if (root / name).is_file()
    }
    result = ScanResult(
        project_dir=str(root),
        files_scanned=files_scanned,
        references=references,
        env_files=env_files,
    )

    used_keys = {r.key for r in references} - BUILTIN_KEYS
    example_names = [n for n in env_files if n in EXAMPLE_FILES]
    concrete_names = [n for n in env_files if n not in EXAMPLE_FILES]
    declared_anywhere = {k for e in env_files.values() for k in e}

    # MISSING: referenced in code, absent from the example/template file.
    # The example file is the team contract; a key not documented there
    # breaks every fresh checkout.
    contract_keys: set[str] = set()
    for name in example_names or list(env_files):
        contract_keys |= set(env_files[name])
    target = example_names[0] if example_names else ".env.example"
    for key in sorted(used_keys - contract_keys):
        result.findings.append(Finding(
            kind="MISSING", severity="error", key=key,
            detail=f"Referenced in code but not declared in {target}",
            locations=_locations(references, key),
        ))

    # UNUSED: declared somewhere, never referenced by any scanned source.
    for key in sorted(declared_anywhere - used_keys - BUILTIN_KEYS):
        where = [n for n, e in env_files.items() if key in e]
        result.findings.append(Finding(
            kind="UNUSED", severity="warning", key=key,
            detail=f"Declared in {', '.join(where)} but never referenced in code",
        ))

    # DRIFT: example file and concrete .env disagree on key sets.
    for ex in example_names:
        for conc in concrete_names:
            only_example = set(env_files[ex]) - set(env_files[conc])
            for key in sorted(only_example):
                result.findings.append(Finding(
                    kind="DRIFT", severity="warning", key=key,
                    detail=f"Present in {ex} but missing from {conc}",
                ))
            missing_keys = {f.key for f in result.findings if f.kind == "MISSING"}
            only_concrete = set(env_files[conc]) - set(env_files[ex]) - missing_keys
            for key in sorted(only_concrete):
                result.findings.append(Finding(
                    kind="DRIFT", severity="info", key=key,
                    detail=f"Present in {conc} but not documented in {ex}",
                ))

    # EMPTY: key declared with empty value in a concrete (non-example) file.
    for name in concrete_names:
        for key, entry in sorted(env_files[name].items()):
            if entry.value == "" and key in used_keys:
                result.findings.append(Finding(
                    kind="EMPTY", severity="error", key=key,
                    detail=f"Declared empty in {name}:{entry.line} but used by code",
                ))

    # .envguardrc ignore_keys (exact names or globs) silence any finding.
    if config.ignore_keys:
        result.findings = [f for f in result.findings
                           if not config.is_ignored(f.key)]
    return result
