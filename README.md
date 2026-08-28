# EnvGuard 🛡️

**Catch environment-variable drift before it crashes your app.**

EnvGuard statically cross-references every environment variable your code
*actually uses* against what your `.env` / `.env.example` files *declare* —
across **JavaScript, TypeScript, Python, Go, Ruby, and PHP** — and reports the
mismatches that otherwise only surface as runtime crashes.

Zero dependencies. Pure Python 3.10+ standard library. No API keys, no
network calls, no telemetry.

---

## Who it's for

- **Teams onboarding new developers** — the #1 first-day failure is a fresh
  checkout crashing because `.env.example` is missing a key someone added to
  code six months ago. EnvGuard makes `.env.example` a *verified* contract.
- **Solo developers with many projects** — point it at any repo and instantly
  see which config keys the code needs and which are documented.
- **CI/CD pipelines** — `envguard scan --ci` exits non-zero when code
  references an undocumented variable, so drift can't merge.
- **Anyone auditing an unfamiliar codebase** — one command inventories every
  piece of external configuration a project depends on.

## What it detects

| Finding | Severity | Meaning |
|---|---|---|
| **MISSING** | error | Referenced in code but not declared in `.env.example` — new checkouts will break |
| **EMPTY** | error | Declared in `.env` with no value, but code reads it |
| **UNUSED** | warning | Declared in an env file but no code references it — dead config |
| **DRIFT** | warning / info | `.env` and `.env.example` have diverged from each other |

## Quick start

```console
# from a clone of this repo (no install needed)
python -m envguard scan path/to/your/project

# or install the `envguard` command
pip install .
envguard scan path/to/your/project
```

Example output:

```
EnvGuard scan of C:\work\my-app
  36 source files, 10 env references, 7 declared keys (.env, .env.example)

[X] MISSING  STRIPE_WEBHOOK_SECRET
    Referenced in code but not declared in .env.example
      at src/api.js:10
[!] UNUSED   LEGACY_FTP_HOST
    Declared in .env.example but never referenced in code

Summary: 1 error(s), 1 warning(s), 0 info
```

## Commands

```console
envguard scan [DIR]            # scan and record to history (.envguard.db)
envguard scan [DIR] --ci       # exit 1 on error findings (for pipelines)
envguard scan [DIR] --json     # machine-readable output on stdout
envguard scan [DIR] --fix      # append MISSING keys to .env.example
envguard scan [DIR] --no-save  # don't record the scan in history
envguard history [DIR]         # table of past scans
envguard serve [DIR]           # web dashboard at http://127.0.0.1:8765
```

**Exit codes:** `0` clean · `1` error findings with `--ci` · `2` usage/config error.

## The dashboard

`envguard serve` starts a local, loopback-only dashboard showing severity
cards, the full findings table, clickable scan history, a **drift trend
chart** (errors/warnings/info per scan over time), and a one-click re-scan
button. Single self-contained HTML file — no CDN, no build step, nothing
leaves your machine.

## What it recognizes in code

| Language | Patterns |
|---|---|
| JS / TS / JSX / Vue / Svelte | `process.env.X` · `process.env["X"]` · `import.meta.env.X` · `const { X, Y: alias } = process.env` (incl. multi-line destructuring) |
| Python | `os.environ["X"]` · `os.environ.get("X")` · `os.getenv("X")` · bare `getenv("X")` |
| Go | `os.Getenv("X")` · `os.LookupEnv("X")` |
| Ruby | `ENV["X"]` · `ENV.fetch("X")` |
| PHP | `getenv('X')` · `$_ENV['X']` · `$_SERVER['X']` |

Runtime-injected keys (`NODE_ENV`, `PATH`, `PORT`, Vite's `MODE`/`DEV`, …) are
ignored, and `node_modules`, virtualenvs, build output, and VCS directories
are skipped automatically.

## Configuration — `.envguardrc`

Optional JSON file in the scanned project's root:

```json
{
  "ignore_keys": ["SENTRY_DSN", "FEATURE_*"],
  "skip_dirs": ["fixtures", "vendor"],
  "extra_patterns": ["config\\.get\\(\\s*['\"](?P<key>[A-Z_][A-Z0-9_]*)['\"]"]
}
```

- **ignore_keys** — exact names or globs that are never reported
- **skip_dirs** — extra directory names to exclude from scanning
- **extra_patterns** — regexes for custom env accessors (must contain a
  named group `(?P<key>...)`); malformed config fails loudly with exit code 2

## CI integration

```yaml
# .github/workflows/envguard.yml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with: { python-version: "3.12" }
- run: pip install envguard-cli   # or: pip install git+https://github.com/manijose1919/envguard
- run: envguard scan . --ci --no-save
```

This repo's own [CI workflow](.github/workflows/ci.yml) runs the 22-test
suite on Linux + Windows across Python 3.10/3.12/3.14, then dogfoods the
scanner against the bundled `demo/` project and asserts it catches the
planted drift.

## Architecture

```
envguard/
  envfile.py    dotenv parser (quotes, export prefix, inline comments)
  scanner.py    polyglot regex source scanner (6 languages + custom patterns)
  config.py     .envguardrc loading + validation
  analyzer.py   cross-referencing -> MISSING / UNUSED / DRIFT / EMPTY
  storage.py    SQLite scan history (.envguard.db in the scanned project)
  report.py     text + JSON reporters
  cli.py        argparse CLI (scan / history / serve, --fix, --ci)
  server.py     stdlib ThreadingHTTPServer JSON API (one connection per request)
  static/index.html   self-contained dashboard
tests/          python -m unittest discover tests
demo/           fixture project with deliberate drift — try:  envguard scan demo
                (`demo/.env` is a committed placeholder file, not a secret)
```

Add `.envguard.db` to your project's `.gitignore`.

**API note:** `GET /api/scans/<id>` for an unknown id returns `200` with an
empty findings list; the dashboard only requests ids from the fetched history.

## Design principles

1. **Zero dependencies** — auditable in one sitting, installs nowhere, runs anywhere.
2. **Regex over AST** — scans code that doesn't even parse (mid-refactor
   branches are exactly where drift is born) and treats six languages uniformly.
3. **Loud failure over silent wrongness** — unknown config options and bad
   regexes are hard errors, never ignored.
4. **Local only** — your env var *names* are reconnaissance gold; the
   dashboard binds 127.0.0.1 and nothing is ever transmitted.

## License

MIT
