# ADR-0011: Run the model engine in a child process that speaks JSON-RPC on stdio

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** devfrx
- **Sources:** tickets [#16](https://github.com/devfrx/jiffin/issues/16) (stack) and [#27](https://github.com/devfrx/jiffin/issues/27) (code structure and protocol)

## Context

The judge and the rewriter ([ADR-0006](0006-judge-rizzo-flow-q4.md),
[ADR-0008](0008-rewrite-conditions-english-statements.md)) need llama.cpp with
the `spark2_5` architecture, merged into llama.cpp on 2026-09-06 (PR #27868),
and they need both logit scoring and text generation.

Ready-made runtimes (checked 2026-09-30):

- **The Rizzo Flow package and server:** no text generation ("no generation"
  in its source), no tags or releases, one maintainer; its server answered
  `/v1/decisions` without a key even with a key configured.
- **llama-cpp-python:** stuck at 0.3.35 (2026-08-17), cannot load `spark2_5`.
  **LLamaSharp** is months behind, and C#.
- **The Rust binding `llama-cpp-2`:** loads it, but compiles llama.cpp and
  requires the CUDA Toolkit.

Where it runs: a failed `GGML_ASSERT` calls `abort()` (verified in `ggml.c`,
b11081), so an engine inside the UI process would take the alert down with it.
How the app talks to a separate engine:

- **Named pipes:** without explicit settings, readable by Everyone and open to
  remote clients.
- **HTTP on loopback:** reachable by every local process.
- **The stdio of a child process:** reachable by no one else.

## Decision

**The engine is our own code**, derived from the ctypes layer of Rizzo Flow
(commit `b9ba007e`, Apache-2.0, with its license and attribution), plus greedy
text generation, which Rizzo Flow lacks. There is no dependency on the Rizzo
Flow package or its server.

- llama.cpp is the official build **b11081 `win-cuda-13.4-x64`**, verified by
  sha256, and updated only after measuring again.
- A parity test compares the engine's d with the values the prototype
  measured, `NO_GIT\sibyl-misura\risultati\alt-rizzo-q4.jsonl`; it is skipped
  when those private files are missing.
- **CUDA, not Vulkan, for now.** On the same GPU, per Rizzo Flow's README:
  49 against 90 ms per decision. Vulkan has open bugs with sliding-window
  models and multiple sequences (llama.cpp #29082, #29221). Vulkan weighs 32 MB
  instead of about 575, and comes back to distribute to others.

**Engine settings:** load the model with direct I/O (fallback: none), not
mmap; a 2,048-token context per question; up to 16 questions per micro-batch;
f16 KV cache.

| Measured on the target machine | Value |
|---|---|
| VRAM with 20 reminders per call | 3,227 MiB loaded, 3,245 MiB at peak (with the 8,192-token default: 4,101 and 4,115) |
| Delay for 20 reminders, p50 / p95 | 498 / 508 ms |
| Engine RAM after a decode, direct I/O | 695 MB working set (605 MB private), 3.7 s to load |
| Engine RAM after a decode, mmap | 2,618 MB working set, 19.8 s to load |
| Engine CPU at rest | 0% |

The RAM rows were measured with a 4,096-token total context and 17 sequences.
With mmap the file's pages stay in the working set: shared and reclaimable, but
enough on their own to break the 2 GB budget under the strictest reading.

**Process.** The engine is a child process of the app. Only the engine goes in
a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so it dies with the app
even when the app crashes. The engine also exits on its own when its stdin
closes, which covers the moment before it is in the Job Object.

**Protocol: JSON-RPC 2.0**, one message per line on stdin and stdout, UTF-8 on
binary pipes, never the console code page; logs go to stderr. At startup the
engine keeps the real stdout on a private descriptor and points descriptor 1
at stderr, so a stray print from a DLL cannot break the protocol.

| Method | Parameters | Result |
|---|---|---|
| `initialize` | `protocol`, model path, settings: context per question, micro-batch, load mode, KV cache | `protocol`, engine version, llama.cpp build, GPU and free VRAM, model type, prompt versions |
| `judge` | normalized context (`app`, `title`, `address`) and statements `[{id, text}]` | `[{id, d}]` and timings |
| `rewrite` | the user's condition | English statement, prompt version, timings |
| `shutdown` | — | `null`; then the app closes stdin and the engine exits |

- **The engine builds the prompts.** The measured question format is tied to
  the model, so the app sends data, not text. Engine, model and prompt versions
  are recorded with every evaluation ([ADR-0014](0014-feedback-data-retention.md)).
- **Version:** `protocol` is an integer, starting at 1 and raised on every
  incompatible change; `initialize` fails on a mismatch. App and engine ship
  together, so the version serves the harness and the records.
- **One request at a time**, in order. No cancellation in the first version:
  the 20 s debounce makes it unnecessary.
- **Errors:** the standard JSON-RPC codes (−32700, −32600, −32601, −32602,
  −32603) and five of ours: −32001 not initialized, −32002 protocol mismatch,
  −32003 model cannot be loaded, −32004 GPU out of memory, −32005 text too long
  for the context. Text is never truncated in silence. `data` holds the detail
  and whether a retry makes sense.

**When the engine fails**, the client:

- notices when the process exits, stdout closes, a message cannot be read, or a
  request times out (starting values: `judge` 15 s, `rewrite` 30 s,
  `initialize` 120 s);
- kills the process and fails the pending requests; the evaluation is recorded
  as an error, not as "no alert", and the tray shows that the engine is down;
- restarts it after 1 s, then 10 s, then 60 s; at the fourth crash within an
  hour it stops, and the tray offers "Riprova" (retry). When `initialize` fails
  because of the model or the VRAM there is no automatic restart: the tray says
  why;
- after a restart, re-evaluates the current context (the cache spares the
  rest) and copies the last stderr lines into the app log.

## Consequences

**Positive**

- A crash in llama.cpp cannot kill the interface, and the CUDA DLLs stay out
  of the UI process.
- The harness drives the same engine through the same protocol
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).
- Nothing is reachable from the network or from other local processes
  ([ADR-0001](0001-keep-data-and-inference-local.md)).

**Negative (accepted)**

- We maintain a derived engine, including the ctypes layer.
- A second executable and a second process
  ([ADR-0015](0015-package-pyinstaller-velopack.md)).
- The protocol must be versioned and kept in step.

**Follow-up**

- The first packaged build checks that the engine starts from the bundle and
  answers `initialize` ([ADR-0015](0015-package-pyinstaller-velopack.md)).
