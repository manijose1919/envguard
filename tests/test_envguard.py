"""EnvGuard test suite (stdlib unittest — run: python -m unittest discover tests)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from envguard.analyzer import analyze
from envguard.cli import main as cli_main
from envguard.config import ConfigError, load_config
from envguard.envfile import parse_env_file
from envguard.report import render_json
from envguard.scanner import scan_file
from envguard.storage import Finding, Store


def run_cli(*args: str) -> int:
    """Invoke the CLI with stdout/stderr captured, returning the exit code."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(list(args))


def write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestEnvFileParser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_parses_quotes_comments_export(self):
        f = write(self.root, ".env", "\n".join([
            "# comment",
            "PLAIN=hello",
            'DQ="quoted value"',
            "SQ='single'",
            "export EXPORTED=yes",
            "INLINE=value  # trailing comment",
            "EMPTY=",
            "not a valid line",
            "PLAIN=overridden",
        ]))
        entries = parse_env_file(f)
        self.assertEqual(entries["PLAIN"].value, "overridden")
        self.assertEqual(entries["DQ"].value, "quoted value")
        self.assertEqual(entries["SQ"].value, "single")
        self.assertEqual(entries["EXPORTED"].value, "yes")
        self.assertEqual(entries["INLINE"].value, "value")
        self.assertEqual(entries["EMPTY"].value, "")
        self.assertNotIn("not", entries)


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def keys(self, rel: str, content: str) -> set[str]:
        p = write(self.root, rel, content)
        return {r.key for r in scan_file(p, self.root)}

    def test_js_patterns(self):
        got = self.keys("app.js", "\n".join([
            "const a = process.env.API_KEY;",
            'const b = process.env["BRACKET_KEY"];',
            "const c = import.meta.env.VITE_URL;",
        ]))
        self.assertEqual(got, {"API_KEY", "BRACKET_KEY", "VITE_URL"})

    def test_destructuring_with_alias_and_default(self):
        got = self.keys("cfg.ts",
            'const { DB_URL: dbConn, REDIS_URL, TIMEOUT = "30" } = process.env;')
        self.assertEqual(got, {"DB_URL", "REDIS_URL", "TIMEOUT"})
        self.assertNotIn("dbConn", got)

    def test_multiline_destructuring(self):
        got = self.keys("multi.js",
            "const {\n  STRIPE_KEY,\n  WEBHOOK_SECRET,\n} = process.env;")
        self.assertEqual(got, {"STRIPE_KEY", "WEBHOOK_SECRET"})

    def test_python_patterns(self):
        got = self.keys("settings.py", "\n".join([
            'import os',
            'a = os.environ["DATABASE_URL"]',
            'b = os.environ.get("CACHE_TTL", "60")',
            'c = os.getenv("SECRET_KEY")',
        ]))
        self.assertEqual(got, {"DATABASE_URL", "CACHE_TTL", "SECRET_KEY"})

    def test_go_patterns(self):
        got = self.keys("main.go",
            'dsn := os.Getenv("GO_DSN")\nv, ok := os.LookupEnv("GO_FLAG")\n')
        self.assertEqual(got, {"GO_DSN", "GO_FLAG"})

    def test_ruby_patterns(self):
        got = self.keys("app.rb",
            'db = ENV["RB_DB"]\ntok = ENV.fetch("RB_TOKEN", "x")\n')
        self.assertEqual(got, {"RB_DB", "RB_TOKEN"})

    def test_php_patterns(self):
        got = self.keys("index.php",
            "<?php\n$a = getenv('PHP_KEY');\n$b = $_ENV['PHP_ENV'];\n"
            "$c = $_SERVER['PHP_SRV'];\n")
        self.assertEqual(got, {"PHP_KEY", "PHP_ENV", "PHP_SRV"})


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def fixture(self):
        write(self.root, "src/index.js",
              "const k = process.env.API_KEY;\n"
              "const m = process.env.MISSING_ONE;\n")
        write(self.root, "src/worker.py",
              'import os\ntoken = os.getenv("EMPTY_TOKEN")\n')
        write(self.root, ".env.example", "API_KEY=\nDEAD_KEY=old\nDRIFTED=x\n")
        write(self.root, ".env",
              "API_KEY=live\nEMPTY_TOKEN=\nEXTRA_LOCAL=1\n")

    def by_kind(self, result, kind):
        return {f.key: f for f in result.findings if f.kind == kind}

    def test_finding_kinds(self):
        self.fixture()
        result = analyze(self.root)

        missing = self.by_kind(result, "MISSING")
        self.assertIn("MISSING_ONE", missing)
        self.assertIn("EMPTY_TOKEN", missing)   # used, not in example
        self.assertEqual(missing["MISSING_ONE"].severity, "error")
        self.assertTrue(any("src/index.js:2" in loc
                            for loc in missing["MISSING_ONE"].locations))

        unused = self.by_kind(result, "UNUSED")
        self.assertIn("DEAD_KEY", unused)
        self.assertIn("EXTRA_LOCAL", unused)
        self.assertNotIn("API_KEY", unused)

        drift = self.by_kind(result, "DRIFT")
        self.assertIn("DEAD_KEY", drift)      # example-only -> warning
        self.assertIn("DRIFTED", drift)
        # EMPTY_TOKEN already reported MISSING; DRIFT-info must be suppressed
        self.assertNotIn("EMPTY_TOKEN", drift)

        empty = self.by_kind(result, "EMPTY")
        self.assertIn("EMPTY_TOKEN", empty)
        self.assertEqual(empty["EMPTY_TOKEN"].severity, "error")

        self.assertTrue(result.has_errors)

    def test_clean_project(self):
        write(self.root, "app.js", "const k = process.env.ONLY_KEY;\n")
        write(self.root, ".env.example", "ONLY_KEY=\n")
        write(self.root, ".env", "ONLY_KEY=value\n")
        result = analyze(self.root)
        self.assertEqual(result.findings, [])
        self.assertFalse(result.has_errors)

    def test_skips_node_modules(self):
        write(self.root, "node_modules/pkg/index.js",
              "const s = process.env.SHOULD_NOT_APPEAR;")
        write(self.root, ".env.example", "")
        result = analyze(self.root)
        self.assertEqual(result.refs_found, 0)

    def test_json_report_roundtrip(self):
        self.fixture()
        payload = json.loads(render_json(analyze(self.root)))
        self.assertIn("findings", payload)
        self.assertGreater(len(payload["findings"]), 0)
        self.assertEqual({"kind", "severity", "key", "detail", "locations"},
                         set(payload["findings"][0]))


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_ignore_keys_glob_silences_findings(self):
        write(self.root, "app.js", "const a = process.env.SENTRY_DSN;\n"
                                   "const b = process.env.FEATURE_NEW_UI;\n"
                                   "const c = process.env.REAL_MISSING;\n")
        write(self.root, ".env.example", "")
        write(self.root, ".envguardrc",
              '{"ignore_keys": ["SENTRY_DSN", "FEATURE_*"]}')
        keys = {f.key for f in analyze(self.root).findings}
        self.assertEqual(keys, {"REAL_MISSING"})

    def test_skip_dirs(self):
        write(self.root, "fixtures/gen.js", "const x = process.env.GENERATED;\n")
        write(self.root, ".envguardrc", '{"skip_dirs": ["fixtures"]}')
        self.assertEqual(analyze(self.root).refs_found, 0)

    def test_extra_patterns(self):
        write(self.root, "app.py", 'value = config.get("CUSTOM_KEY")\n')
        write(self.root, ".envguardrc",
              '{"extra_patterns": '
              '["config\\\\.get\\\\(\\\\s*[\'\\"](?P<key>[A-Z_][A-Z0-9_]*)[\'\\"]"]}')
        refs = {r.key for r in analyze(self.root).references}
        self.assertIn("CUSTOM_KEY", refs)

    def test_malformed_rc_raises(self):
        write(self.root, ".envguardrc", "{not json")
        with self.assertRaises(ConfigError):
            load_config(self.root)

    def test_unknown_option_raises(self):
        write(self.root, ".envguardrc", '{"ignore_key": ["TYPO"]}')
        with self.assertRaises(ConfigError):
            load_config(self.root)


class TestFixMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_fix_appends_missing_keys_and_clears_findings(self):
        write(self.root, "app.js", "const k = process.env.NEEDS_DOCS;\n")
        write(self.root, ".env.example", "EXISTING=1\n")
        rc = run_cli("scan", str(self.root), "--fix", "--no-save", "--ci")
        self.assertEqual(rc, 0)  # MISSING was fixed before the report
        example = (self.root / ".env.example").read_text(encoding="utf-8")
        self.assertIn("NEEDS_DOCS=", example)
        self.assertIn("EXISTING=1", example)  # original content preserved
        self.assertFalse(any(f.kind == "MISSING"
                             for f in analyze(self.root).findings))

    def test_fix_creates_example_file_when_absent(self):
        write(self.root, "app.js", "const k = process.env.BRAND_NEW;\n")
        run_cli("scan", str(self.root), "--fix", "--no-save")
        self.assertIn("BRAND_NEW=",
                      (self.root / ".env.example").read_text(encoding="utf-8"))

    def test_malformed_rc_exits_with_usage_error(self):
        write(self.root, "app.js", "const k = process.env.X_KEY;\n")
        write(self.root, ".envguardrc", "{broken")
        self.assertEqual(run_cli("scan", str(self.root), "--no-save"), 2)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.db"
        self.addCleanup(self.tmp.cleanup)

    def test_save_and_read_back(self):
        findings = [
            Finding("MISSING", "error", "A_KEY", "detail", ("f.js:1",)),
            Finding("UNUSED", "warning", "B_KEY", "detail"),
        ]
        with Store(self.db) as store:
            scan_id = store.save_scan("/proj", 3, 5, 2, findings)
            scans = store.list_scans()
            self.assertEqual(scans[0]["errors"], 1)
            self.assertEqual(scans[0]["warnings"], 1)
            self.assertEqual(scans[0]["infos"], 0)
            got = store.get_findings(scan_id)
            self.assertEqual(got[0]["severity"], "error")   # errors sort first
            self.assertEqual(got[0]["locations"], ["f.js:1"])
            self.assertEqual(store.latest_scan_id(), scan_id)

    def test_empty_scan_counts_are_zero_not_null(self):
        with Store(self.db) as store:
            store.save_scan("/proj", 0, 0, 0, [])
            s = store.list_scans()[0]
            self.assertEqual((s["errors"], s["warnings"], s["infos"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
