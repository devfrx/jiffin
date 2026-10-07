# ADR-0001: Keep all data and inference on the user's machine

- **Status:** Accepted; amended by [ADR-0028](0028-read-the-situations-in-core.md) (Jiffin reads states, never texts)
- **Date:** 2026-09-25
- **Deciders:** devfrx
- **Sources:** product premises of the [decision map](https://github.com/devfrx/jiffin/issues/1); tickets [#15](https://github.com/devfrx/jiffin/issues/15) (feedback data) and [#16](https://github.com/devfrx/jiffin/issues/16) (stack)

## Context

Jiffin shows a reminder when the user's current work makes a condition true.
To know the current work it reads, all day long, the active app, the window
title and the address of the browser tab. Titles and addresses routinely name
clients, documents, searches and private pages; reminder texts are personal
too. Whoever evaluates the conditions sees all of it.

- **Cloud inference** (a hosted LLM, or a backend like Jev's TypeSafe):
  more accurate out of the box and no GPU needed, but every context change
  leaves the machine, and it needs an account, a network and trust in a third
  party.
- **Local inference:** nothing leaves the machine, but the model must be
  accurate enough and fit the hardware. The target machine is a laptop with an
  8 GB NVIDIA RTX 4060 and 16 GB of RAM.

## Decision

All contexts, reminders, evaluations and feedback stay on the user's machine,
and every model runs locally. This is a property of the product, not an
optimisation.

- No telemetry, no analytics, no crash reports sent anywhere.
- The inference engine is not reachable from the network or from other local
  processes ([ADR-0011](0011-engine-child-process-json-rpc.md)).
- The app's only network traffic is the one-time model download at a pinned
  revision and the update check
  ([ADR-0015](0015-package-pyinstaller-velopack.md)).
- Personal data never enters the repository, the issues or CI: the repository
  holds synthetic fixtures only ([ADR-0017](0017-evaluation-harness-subpackage.md)).

## Consequences

**Positive**

- Nothing to trust but the machine itself; no account.
- Works offline once the model is on disk.

**Negative (accepted)**

- Accuracy is bounded by what fits in about 4 GiB of VRAM
  ([ADR-0003](0003-acceptance-thresholds.md)).
- An NVIDIA GPU is required: on the CPU the chosen model takes 8.7–20.7 s per
  event ([ADR-0006](0006-judge-rizzo-flow-q4.md)).
- A 2.4 GiB model download on first run.

**Follow-up**

- Learning from feedback, planned after the first version, must stay local
  as well.
