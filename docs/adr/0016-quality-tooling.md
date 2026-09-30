# ADR-0016: Enforce quality with Ruff, mypy, pytest and import-linter, in pre-commit and Windows CI

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** ticket [#29](https://github.com/devfrx/jiffin/issues/29) (quality tools)

## Context

The stack is Python 3.13 with uv and QML with PySide6
([ADR-0009](0009-qt-quick-pyside6-interface.md)), with import boundaries to
enforce ([ADR-0012](0012-package-structure-ports.md)). Unit tests use a fake
model; integration tests need the real model and the GPU, so they run only on
the owner's machine. Versions were checked on PyPI and on the official releases
on 2026-09-30.

Type checkers considered: mypy, pyright, basedpyright and ty. Qt checks the
PySide6 type stubs with mypy; mypy is pure Python, with no Node. basedpyright
is a serious alternative, but nobody verifies it against PySide6. ty is in beta,
with 0.0.x versions that may break with every release.

## Decision

**Python**

| What | Tool | Version |
|---|---|---|
| Formatter and linter | Ruff | 0.16.9 |
| Type checker | mypy, `strict`, with the pydantic plugin | 2.3.1 |
| Tests | pytest; pytest-qt for view-models and QML | 9.1.1; 4.5.0 |
| Coverage | coverage with pytest-cov | 7.16.2; 7.1.0 |
| Boundaries between parts | import-linter | 2.15 |

- **Ruff:** the default rule set of 0.16; lines of 100 characters, as in the
  Rizzo Flow code the engine derives from, so derived files stay comparable to
  the original; the version pinned exactly, because Ruff's minor releases are
  the ones that may break.
- **mypy:** Qt properties are written as `Property(type, get, set, notify=...)`;
  the setter-decorator form is reported by mypy as a redefinition
  (python/mypy#17406, still open). Per-module exceptions only when needed, each
  with its reason written next to it. Pylance in the editor uses pyright and may
  disagree: mypy is authoritative.
- **pytest:** native `[tool.pytest]` configuration and pytest 9's `strict`
  mode. Unit tests in `tests/unit`, with the fake model, the simulated clock and
  SQLite on a temporary file. Integration tests in `tests/integration`, marked
  `integration` as in Rizzo Flow, excluded by default and run only on the
  owner's machine with `uv run pytest -m integration`. Tests that read the
  private sample take it from `NO_GIT` and skip when it is missing; no personal
  data enters the repository.
- **pytest-qt 4.5.0** supports PySide6 and Python 3.13, and its own Windows CI
  runs PySide6 6.11.2. It serves the view-models and a check that loads every
  QML file and fails if Qt prints a warning.
- **Coverage:** measured in CI, with a 90% floor only on `core` and `protocol`,
  which are pure logic. The engine process is measured with coverage's
  `patch = subprocess`, since pytest-cov 7 no longer measures subprocesses on
  its own.
- **import-linter** contracts, with `include_external_packages` so PySide6 can
  be forbidden too:
  - PySide6 only in `ui` and `app`;
  - `core` and `protocol` import nothing else from `jiffin`;
  - `engine` imports only `protocol`, and nothing imports `engine`;
  - `ui` imports none of `engine`, `client`, `platform` and `store`;
  - the adapters (`client`, `platform`, `store`) do not import each other.

**QML**

- `pyside6-qmllint` and `pyside6-qmlformat`, from the PySide6-Essentials
  6.11.2 wheel.
- First `pyside6-project build`, which writes `.qmltypes` and `qmldir` for the
  Python types registered with `@QmlElement`; then
  `pyside6-qmllint --max-warnings 0` on every file.
- Never `pyside6-project qmllint`: it ignores errors and always exits with 0
  (verified in the PySide6 6.11.2 source).
- `.qmllint.ini` and `.qmlformat.ini` live in the repository. qmlformat has no
  check mode: it runs with `-i` inside pre-commit, which fails when a file
  changes.

**pre-commit 4.6.2**

- Local hooks run through `uv run`, so every version lives in one place, the
  lockfile: Ruff (check with fixes, and format), mypy, import-linter, qmllint
  and qmlformat, `uv lock --check`.
- From `pre-commit/pre-commit-hooks` v6.0.0: trailing whitespace, end of files,
  valid YAML and TOML, large files — the last one keeps a GGUF out by mistake.
- Tests are not hooks: they run in CI and by hand.
- prek 0.5.4 reads the same configuration but is still 0.x and calls itself
  "pretty new"; switching later changes nothing.

**CI**

- GitHub Actions on `windows-2025`, spelled out (`windows-latest` points there
  today).
- `actions/checkout` v7.0.1 and `astral-sh/setup-uv` v10.2.0, pinned by SHA;
  then `uv sync --locked`, `uv run pre-commit run --all-files` and
  `uv run pytest` with coverage. Python comes from uv's managed builds
  ([ADR-0013](0013-sqlite-storage.md)).
- On every push and every pull request.
- The free plan gives private repositories 2,000 minutes a month; without a
  payment method, jobs stop when the minutes run out instead of costing money.
  A run should take about 5 minutes (assumed); even counting Windows minutes
  double, 100 runs a month use 1,000.
- Version upgrades are manual and deliberate — `uv lock --upgrade-package`,
  then the suite — with no bot opening pull requests.

## Consequences

**Positive**

- One source of truth for tool versions: the lockfile.
- The boundaries of [ADR-0012](0012-package-structure-ports.md) cannot erode
  unnoticed.

**Negative (accepted)**

- The editor (Pylance) and mypy may disagree.
- qmlformat rewrites files inside pre-commit instead of only checking them.
- Integration tests never run in CI: there is no GPU there.

**Follow-up**

- The harness code goes through the same hooks
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).
