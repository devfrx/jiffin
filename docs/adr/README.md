# Architecture decision records

Each record explains one decision: the context, the options, what was chosen
and what it costs. Records are append-only in substance: when a decision
changes, a new record replaces it and the old one is marked
`Superseded by ADR-XXXX`. New records start from [template.md](template.md).

The decisions below were taken on the project's
[decision map](https://github.com/devfrx/jiffin/issues/1), in Italian; each
record links the tickets it comes from.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-keep-data-and-inference-local.md) | Keep all data and inference on the user's machine | Accepted |
| [0002](0002-apache-license-english-repository.md) | License the code under Apache-2.0 and write the repository in English | Accepted |
| [0003](0003-acceptance-thresholds.md) | Accept the first version on a real working day, against fixed thresholds | Accepted |
| [0004](0004-context-identity.md) | Define a context as app, window title and tab address | Accepted; amended by [0018](0018-keep-exe-in-the-app-name.md) |
| [0005](0005-browser-address-ui-automation.md) | Read the browser address with UI Automation | Accepted |
| [0006](0006-judge-rizzo-flow-q4.md) | Judge conditions with Rizzo Flow 4B in Q4_K_M | Accepted |
| [0007](0007-single-stage-pipeline.md) | Judge every active reminder in one stage, without retrieval | Accepted; amended by [0019](0019-five-second-debounce.md) |
| [0008](0008-rewrite-conditions-english-statements.md) | Rewrite conditions as English statements with the judge model | Accepted |
| [0009](0009-qt-quick-pyside6-interface.md) | Build the interface with Qt Quick and PySide6 | Accepted |
| [0010](0010-windows-11-look-own-components.md) | Follow the Windows 11 look with our own QML components | Accepted |
| [0011](0011-engine-child-process-json-rpc.md) | Run the model engine in a child process that speaks JSON-RPC on stdio | Accepted |
| [0012](0012-package-structure-ports.md) | Structure the code as one package with eight parts and three ports | Accepted |
| [0013](0013-sqlite-storage.md) | Store data in one SQLite file with the standard sqlite3 module | Accepted |
| [0014](0014-feedback-data-retention.md) | Keep evaluations for 30 days and answered alerts until the reminder is deleted | Accepted |
| [0015](0015-package-pyinstaller-velopack.md) | Package with PyInstaller and Velopack, and download the model on first run | Accepted |
| [0016](0016-quality-tooling.md) | Enforce quality with Ruff, mypy, pytest and import-linter, in pre-commit and Windows CI | Accepted |
| [0017](0017-evaluation-harness-subpackage.md) | Ship the evaluation harness as a subpackage, outside the app bundle | Accepted |
| [0018](0018-keep-exe-in-the-app-name.md) | Keep `.exe` in the app name the judge sees | Accepted |
| [0019](0019-five-second-debounce.md) | Evaluate a context after 5 s in the foreground | Accepted |
