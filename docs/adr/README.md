# Architecture decision records

Each record explains one decision: the context, the options, what was chosen
and what it costs. Records are append-only in substance: when a decision
changes, a new record replaces it and the old one is marked
`Superseded by ADR-XXXX`. New records start from [template.md](template.md).

Most decisions below were taken on the project's decision maps, in Italian:
the [first version's](https://github.com/devfrx/jiffin/issues/1),
[version 0.2's](https://github.com/devfrx/jiffin/issues/75) and
[version 0.3's](https://github.com/devfrx/jiffin/issues/119). Each record
links the tickets it comes from.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-keep-data-and-inference-local.md) | Keep all data and inference on the user's machine | Accepted; amended by [0028](0028-read-the-situations-in-core.md) |
| [0002](0002-apache-license-english-repository.md) | License the code under Apache-2.0 and write the repository in English | Accepted; amended by [0026](0026-italian-in-language-files.md) |
| [0003](0003-acceptance-thresholds.md) | Accept the first version on a real working day, against fixed thresholds | Accepted; amended by [0022](0022-acceptance-thresholds-v0-2.md), [0025](0025-kept-quiet-not-missed.md), [0029](0029-learn-from-answers-per-place.md) and [0031](0031-acceptance-thresholds-v0-3.md) |
| [0004](0004-context-identity.md) | Define a context as app, window title and tab address | Accepted; amended by [0018](0018-keep-exe-in-the-app-name.md) and [0028](0028-read-the-situations-in-core.md) |
| [0005](0005-browser-address-ui-automation.md) | Read the browser address with UI Automation | Accepted |
| [0006](0006-judge-rizzo-flow-q4.md) | Judge conditions with Rizzo Flow 4B in Q4_K_M | Accepted |
| [0007](0007-single-stage-pipeline.md) | Judge every active reminder in one stage, without retrieval | Accepted; amended by [0019](0019-five-second-debounce.md) and [0029](0029-learn-from-answers-per-place.md) |
| [0008](0008-rewrite-conditions-english-statements.md) | Rewrite conditions as English statements with the judge model | Accepted; amended by [0020](0020-read-the-time-in-core.md) and [0028](0028-read-the-situations-in-core.md) |
| [0009](0009-qt-quick-pyside6-interface.md) | Build the interface with Qt Quick and PySide6 | Accepted |
| [0010](0010-windows-11-look-own-components.md) | Follow the Windows 11 look with our own QML components | Accepted; amended by [0023](0023-window-frame.md) |
| [0011](0011-engine-child-process-json-rpc.md) | Run the model engine in a child process that speaks JSON-RPC on stdio | Accepted; amended by [0027](0027-light-sleep-of-the-engine.md) |
| [0012](0012-package-structure-ports.md) | Structure the code as one package with eight parts and three ports | Accepted; amended by [0026](0026-italian-in-language-files.md) and [0028](0028-read-the-situations-in-core.md) |
| [0013](0013-sqlite-storage.md) | Store data in one SQLite file with the standard sqlite3 module | Accepted; amended by [0027](0027-light-sleep-of-the-engine.md), [0028](0028-read-the-situations-in-core.md) and [0029](0029-learn-from-answers-per-place.md) |
| [0014](0014-feedback-data-retention.md) | Keep evaluations for 30 days and answered alerts until the reminder is deleted | Accepted; amended by [0021](0021-one-alert-per-unit.md), [0027](0027-light-sleep-of-the-engine.md), [0028](0028-read-the-situations-in-core.md) and [0029](0029-learn-from-answers-per-place.md) |
| [0015](0015-package-pyinstaller-velopack.md) | Package with PyInstaller and Velopack, and download the model on first run | Accepted |
| [0016](0016-quality-tooling.md) | Enforce quality with Ruff, mypy, pytest and import-linter, in pre-commit and Windows CI | Accepted |
| [0017](0017-evaluation-harness-subpackage.md) | Ship the evaluation harness as a subpackage, outside the app bundle | Accepted; amended by [0021](0021-one-alert-per-unit.md), [0028](0028-read-the-situations-in-core.md) and [0031](0031-acceptance-thresholds-v0-3.md) |
| [0018](0018-keep-exe-in-the-app-name.md) | Keep `.exe` in the app name the judge sees | Accepted |
| [0019](0019-five-second-debounce.md) | Evaluate a context after 5 s in the foreground | Accepted; amended by [0027](0027-light-sleep-of-the-engine.md) and [0028](0028-read-the-situations-in-core.md) |
| [0020](0020-read-the-time-in-core.md) | Read the time of a condition with our own grammar in `core` | Accepted; amended by [0026](0026-italian-in-language-files.md) and [0028](0028-read-the-situations-in-core.md) |
| [0021](0021-one-alert-per-unit.md) | Ring a reminder once per occasion or per instance of its time, and keep perennial reminders | Accepted; amended by [0026](0026-italian-in-language-files.md), [0028](0028-read-the-situations-in-core.md), [0029](0029-learn-from-answers-per-place.md) and [0030](0030-undo-and-reopen.md) |
| [0022](0022-acceptance-thresholds-v0-2.md) | Accept version 0.2 with false alarms counted once per pair, target 10 and cap 20 | Accepted; amended by [0025](0025-kept-quiet-not-missed.md) and [0031](0031-acceptance-thresholds-v0-3.md) |
| [0023](0023-window-frame.md) | Close every window with an X, and drag every window but the alerts | Accepted |
| [0024](0024-hold-and-hide-alerts.md) | Hold alerts while a window is in full screen or Jiffin is paused, and hide them from screen capture | Accepted; amended by [0027](0027-light-sleep-of-the-engine.md) |
| [0025](0025-kept-quiet-not-missed.md) | Leave the pairs kept quiet as already reminded out of the missed reminders | Accepted; amended by [0029](0029-learn-from-answers-per-place.md) |
| [0026](0026-italian-in-language-files.md) | Write the code in English, and keep the app's Italian in language files | Accepted |
| [0027](0027-light-sleep-of-the-engine.md) | Free the GPU with a light sleep of the engine, and wake it inside the debounce | Accepted |
| [0028](0028-read-the-situations-in-core.md) | Read the situations of a condition in `core`, from states and never from texts | Accepted |
| [0029](0029-learn-from-answers-per-place.md) | Learn from Not here and Remind here, per place, with a threshold per reminder that only goes down | Accepted |
| [0030](0030-undo-and-reopen.md) | Hold an answer for 5 s with Undo, and keep completed reminders to reopen them | Accepted |
| [0031](0031-acceptance-thresholds-v0-3.md) | Accept version 0.3 with the thresholds of 0.2, plus the engine's sleep and its late wakes | Accepted |
