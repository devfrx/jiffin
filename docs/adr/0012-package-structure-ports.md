# ADR-0012: Structure the code as one package with eight parts and three ports

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** ticket [#27](https://github.com/devfrx/jiffin/issues/27) (code structure)

## Context

With the stack decided ([ADR-0009](0009-qt-quick-pyside6-interface.md),
[ADR-0011](0011-engine-child-process-json-rpc.md)), the code needs modules and
boundaries: interface, app logic, context sources, engine, storage, harness.
Ports and adapters are worth their cost only where there is a real second use
today: a fake model in unit tests, a recorded day replayed by the harness,
simulated time.

Threading constraints found on PySide6 6.11.2 (verified in the sources and in
a local test):

- QtAsyncio is a technical preview, and its `subprocess_exec` raises
  `NotImplementedError`.
- qasync handles processes on Windows, but its last release is from
  2025-08-28 and its README declares Python < 3.14.
- The blocking `QProcess.waitForReadyRead` does not release the GIL.

## Decision

**One Python package, `jiffin`, under `src/`**, the layout `uv init` creates
since uv 0.12, with the `uv_build` backend. The harness and the tests keep
their dependencies in `[dependency-groups]`, not in separate packages.

| Part | Contents | May import from `jiffin` |
|---|---|---|
| `core` | Product rules: context and normalization, reminders and revisions, debounce, cache, threshold, alert rules (repetition, snooze, "not here"), feedback; the three ports. No Qt, no Win32, no I/O. | nothing |
| `protocol` | The engine protocol: message types in pydantic 2, as in the Rizzo Flow code the engine derives from; methods, error codes, version. | nothing |
| `engine` | The child process: llama.cpp ctypes layer and shared-prefix scoring derived from Rizzo Flow; greedy generation; versioned prompts; JSON-RPC server on stdio. | `protocol` |
| `client` | The engine as the app sees it: the model file (download and check), starting the child, Job Object, handshake, requests with timeouts, restarts. The adapter of the model port. | `core`, `protocol` |
| `platform` | Windows without Qt: active app, title, and address through UI Automation (COM in the multithreaded apartment). The adapter of the context port. | `core` |
| `store` | Storage ([ADR-0013](0013-sqlite-storage.md)). | `core` |
| `ui` | Qt Quick: our QML components, view-models exposed with `@QmlElement` and `@QmlSingleton`, tray, global shortcut, the glass recipe ([ADR-0010](0010-windows-11-look-own-components.md)). | `core` |
| `app` | The composition root: creates the adapters, connects the ports, starts the threads and Qt. | everything |

**Import rules**, enforced by import-linter
([ADR-0016](0016-quality-tooling.md)):

- only `ui` and `app` import PySide6;
- only `engine` loads the llama.cpp DLLs;
- `core` and `protocol` import nothing else from `jiffin`;
- `engine` imports only `protocol`, and nothing imports `engine`;
- `ui` imports none of `engine`, `client`, `platform` and `store`;
- the adapters (`client`, `platform`, `store`) do not import each other.

**Three ports, no more:**

| Port | In the app | In tests and in the harness |
|---|---|---|
| Model (`judge`, `rewrite`) | the engine, in the child process | a fake model in unit tests; the real engine in the harness and in integration tests |
| Context | Windows and UI Automation | a replayed day or synthetic fixtures |
| Clock | the system time | simulated time |

Storage and interface have no port: storage is tested on a temporary SQLite
file, and `core` notifies the interface through callbacks. No dependency
injection container: the wiring lives in `app`.

**Threads:**

- **main:** Qt, QML, tray, global shortcut;
- **context:** `platform` reads window, title and address, and queues events;
- **worker:** one thread owns `core`, the store and the engine client. It takes
  one event at a time from a queue: contexts, user commands, deadlines. `core`
  has no locks, and the database has one connection, on this thread;
- **worker to interface:** Qt signals emitted on the worker, connected to
  `@Slot` methods of objects living on the main thread; with the automatic
  connection type those methods run on the main thread;
- **interface to worker:** commands put on the queue, without waiting;
- **inside the client:** the standard library's `subprocess`, with one thread
  reading stdout and one draining stderr.

**Entry points:** `jiffin.app:main` for the interface and `jiffin.engine:main`
for the engine; in development, `python -m jiffin` and
`python -m jiffin.engine`.

Why these choices:

- **Three ports** only where a second use exists today; an interface for every
  piece would have no use.
- **One package:** uv's workspaces are for several linked packages, and a root
  module with subpackages is the normal case. A workspace would still share one
  environment, so the import rules would be needed anyway.
- **A worker thread and a queue, not asyncio,** because of the QtAsyncio,
  qasync and QProcess limits above; the client uses `subprocess` for the same
  reason.
- **Not `setContextProperty`**, which the Qt 6.11 documentation discourages in
  favour of singletons and properties.

## Consequences

**Positive**

- A pure `core`, testable without Qt, Windows or a GPU.
- Boundaries checked by a tool, not by memory.
- One owner thread: no locks in `core`, no contention on the database.

**Negative (accepted)**

- One worker serializes everything; with the debounce this costs nothing
  measurable.
- Signals and slots add boilerplate between the worker and the interface.

**Follow-up**

- An architecture diagram in `docs/design/` once the app is wired.
