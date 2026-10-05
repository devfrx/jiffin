# ADR-0017: Ship the evaluation harness as a subpackage, outside the app bundle

- **Status:** Accepted; amended by [ADR-0021](0021-one-alert-per-unit.md) (what the commands replay and report from 0.2; the statements page writes the time with `ui/words.py`)
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** ticket [#30](https://github.com/devfrx/jiffin/issues/30) (harness)

## Context

The first version is accepted by measuring a real working day
([ADR-0003](0003-acceptance-thresholds.md)): delay, missed reminders, false
alarms, VRAM, RAM, CPU and battery. The same measurements must be repeatable
whenever the model, the prompts or llama.cpp change, and as the number of
active reminders grows, the main risk of the single-stage pipeline
([ADR-0007](0007-single-stage-pipeline.md)).

The measurement prototype (`NO_GIT\sibyl-misura`) proved the method, but it
re-implements the product's rules on its own (`stima_giornata.py`), mixes
Italian and English, and carries Laya, retrieval and PyTorch, none of which the
product uses any more. The recorded days contain personal data.

## Decision

**Form and place.**

- The harness is the subpackage `jiffin.harness`, run with
  `python -m jiffin.harness <command>`, in the same package as the app
  ([ADR-0012](0012-package-structure-ports.md)).
- It uses `core` (with the simulated clock and the replayed context), `client`,
  `protocol` and `store`; never `ui` or `platform`, and nothing imports it.
  import-linter enforces both ([ADR-0016](0016-quality-tooling.md)).
- It is not part of the app: the PyInstaller spec excludes it by name, even
  though the app never imports it
  ([ADR-0015](0015-package-pyinstaller-velopack.md)).
- Its dependencies are a `harness` group with `psutil` only. Metrics (AUROC,
  percentiles, bootstrap) are pure Python: the data are hundreds of pairs, and
  scikit-learn would bring numpy and scipy along.
- From the prototype it takes only what it needs: reading the sample and its
  labels, the metrics, the estimate of a day. Rewritten in English
  ([ADR-0002](0002-apache-license-english-repository.md)).
- The engine is the app's own, started through `client`, with the same
  protocol ([ADR-0011](0011-engine-child-process-json-rpc.md)).

**Commands** (option names translated into English from the ticket):

| Command | What it does | What it writes |
|---|---|---|
| `snapshot` | copies the app's log through SQLite's backup API, also while the app runs | the copy, in the data folder |
| `statements` | lists, for every reminder, the condition and its English statement, for the check on the acceptance day | a page with the real texts |
| `label` | prepares the (context, reminder) pairs to judge: all of them for LLM-assisted labelling, a share for the owner, with a page like the one used on 2026-09-28 | the labels, as JSON |
| `report` | from a copy and its labels: delay p50 and p95, missed reminders, false alarms per day, evaluations per hour, engine errors, compared with the thresholds of [ADR-0003](0003-acceptance-thresholds.md) | a summary of numbers only, fit for an issue, plus a detail page with the texts |
| `replay` | replays the copy's contexts through `core` with simulated time: at another threshold (from the stored `d`, no engine), with more active reminders (extra synthetic fixtures), or with another engine | as `report` |
| `sample` | runs the labelled sample from `NO_GIT\sibyl-campione` through the engine: AUROC, recall at fixed false alarms, per condition class | a summary of numbers only |
| `monitor` | during the acceptance day, every 5 s: CPU and RAM of app, engine and browsers, VRAM through `nvidia-smi`, battery state | a CSV of numbers only |

- **Growing reminders:** `replay --reminders 20,40,80` adds synthetic
  reminders up to each level and reports false alarms per day and delay for
  each.
- **Changing the engine:** when the model, the prompts or llama.cpp change,
  `sample` and `replay` compare the new build with the previous one. Engine
  updates ship only after this.
- **`replay` and `sample` run with the app closed.** Two engines together would
  need about 6.4 GiB of VRAM out of 8 (estimated from
  [ADR-0011](0011-engine-child-process-json-rpc.md)); the harness checks the free
  VRAM before starting, and stops if it is not enough.
- **The CPU browsers spend on accessibility** is not measured by the harness,
  which does not import `platform`. A benchmark in `tests/integration` does it:
  the app's own UI Automation reads for 5 minutes, against 5 minutes without
  reads, with the browser in the foreground
  ([ADR-0005](0005-browser-address-ui-automation.md)).

**Personal data.**

- Everything that contains titles, addresses or reminder texts — log copies,
  labels, pages, details — goes to a data folder outside the repository. The
  default is `NO_GIT\jiffin-prove\`, next to the other private working files;
  `--data` changes it.
- The log copy is deleted when the analysis is done
  ([ADR-0013](0013-sqlite-storage.md)).
- The repository holds only code and synthetic fixtures, in `tests/fixtures`:
  invented contexts and reminders, in Italian. The same fixtures are the extra
  reminders of `replay --reminders`.
- Issues get only the number-only summaries.
- `.gitignore` excludes `*.db`, `*.gguf` and `jiffin-prove/`, as a safety net.

**A schema addition.** To measure the delay from the context change to the
alert, each evaluation also records when its context came to the foreground,
`context_since`; the delay is `alert.shown_at − evaluation.context_since`
([ADR-0013](0013-sqlite-storage.md)).

Why:

- **A subpackage, not a workspace member or a scripts folder:** it stays under
  the same hooks, type checker and import contracts, and it uses the real
  `core`, so the pipeline it measures is the one the app runs.
- **Replay goes through `core` with simulated time**, instead of re-deriving the
  rules as the prototype did: two copies of the rules would drift apart.
- **One input format for recorded days: the app's own log.** The prototype's
  capture stays where it is; the day of 2026-09-28 is converted once if a
  comparison is needed.

## Consequences

**Positive**

- Every threshold of [ADR-0003](0003-acceptance-thresholds.md) is measurable
  with one tool, without personal data leaving the data folder.
- Engine changes are measured the same way every time.

**Negative (accepted)**

- `replay` and `sample` need the app closed, because of the VRAM.
- The harness lives in the app's package and must respect its boundaries.

**Follow-up**

- `context_since` enters the first migration.
