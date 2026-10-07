# ADR-0027: Free the GPU with a light sleep of the engine, and wake it inside the debounce

- **Status:** Accepted
- **Date:** 2026-10-07
- **Deciders:** devfrx
- **Sources:** the [0.3 decision map](https://github.com/devfrx/jiffin/issues/119): tickets [#120](https://github.com/devfrx/jiffin/issues/120) (research), [#121](https://github.com/devfrx/jiffin/issues/121) (return times, plugged in), [#138](https://github.com/devfrx/jiffin/issues/138) (on battery) and [#122](https://github.com/devfrx/jiffin/issues/122) (decision); amends [ADR-0011](0011-engine-child-process-json-rpc.md), [ADR-0013](0013-sqlite-storage.md), [ADR-0014](0014-feedback-data-retention.md), [ADR-0019](0019-five-second-debounce.md) and [ADR-0024](0024-hold-and-hide-alerts.md)

## Context

The owner asked to free the GPU when Jiffin does not need it, without making
an alert later ([#119](https://github.com/devfrx/jiffin/issues/119)). In 0.2
the engine stays loaded all day, also while paused: 3,247 MiB of VRAM on the
monitor of the acceptance day. An alert waits for 5 s of stable context
([ADR-0019](0019-five-second-debounce.md)), and loading the model takes about
4 s ([ADR-0011](0011-engine-child-process-json-rpc.md)): one after the other,
9 s.

Local runtimes free a model after a time without use: Ollama and llama-swap do
([#120](https://github.com/devfrx/jiffin/issues/120)); Ollama's `keep_alive`
is 5 minutes by default. Two levels were possible: a **light sleep**, which
frees the model and its context and keeps the process alive, and a **deep
sleep**, which ends the process.

Measured on the owner's laptop, an RTX 4060 Laptop with 8 GiB
([#121](https://github.com/devfrx/jiffin/issues/121) plugged in and in use,
[#138](https://github.com/devfrx/jiffin/issues/138) on battery):

| | Light sleep | Deep sleep |
|---|---|---|
| Frees | 3.1 of 3.2 GiB of VRAM and 3.5 GiB of RAM; plugged in, the card stays in D0 | everything; the card goes to D3 in about 6 s |
| Back, plugged in | 2.3–3.7 s | 4.1–6.0 s with the file partly cached, 8.0–9.7 s cold: little RAM is free, and the file is read again from disk |
| Back, on battery | 2.8–3.2 s | 4.7–8.0 s |

- A spare process saves only its start, about 0.7 s; loading CUDA's DLLs
  costs 0.8–4.5 s.
- On real days the engine served 21–40 times in 5–6 hours. Sleeping 5 minutes
  after the last need, it would have come back 14 times on 2026-10-05 and 8 on
  2026-10-06, asleep 68% and 57% of the time.
- Plugged in, the card with the engine loaded sits in P8 at 1.6 W. On
  battery it goes to D3 by itself even with the engine loaded, 10–34 s after
  the last judgement: there the loaded engine costs about 1 W and the light
  sleep nothing, inside a noise of 1.4–1.8 W over about 37 W. A judgement with
  the card in D3 takes 1.22 s instead of about 0.5.
- Under a game holding 6 GiB, Windows takes half of the engine's VRAM away,
  and a judgement goes from 0.37 to about 2 s.
- Without a warm-up, the first judgement after a load costs 0.1–0.25 s more.
- `nvidia-smi` wakes the card; Windows' performance counters, read once a
  second, do not.

## Decision

**One level: the light sleep.** The engine frees its model and context, 3.1
GiB of VRAM and 3.5 GiB of RAM, and its process stays alive. Deep sleep is
rejected: it comes back after the 5 s. A technical choice, delegated by the
owner; the owner's constraint holds: no alert later than in 0.2.

**When it sleeps.**

- **5 minutes after the engine was last needed**, for a judgement or for a
  statement to write.
- **At once when nothing is in front**: Pause, a locked screen, the PC asleep,
  a window in full screen, a private window or one of Jiffin's. Nothing is
  judged there.
- **On battery, no rule more**: the card goes to D3 by itself, and the 5
  minutes free the RAM.

**When it comes back.**

- **When a context arrives with at least one judgement not in the cache.**
  The reload starts at once, alongside the 5 s. A context whose judgements are
  all cached wakes nothing: 108 evaluations of 148 did not call the engine on
  2026-10-05, 78 of 99 on 2026-10-06. The same when a statement must be
  written.
- **A warm-up judgement ends every load**, inside `initialize`: the reload
  pays for it, inside the 5 s.
- **A safety net.** A judgement or a rewriting asked while the engine sleeps
  wakes it and waits: no evaluation fails because the engine slept. A reload
  longer than the 5 s makes its alert come as soon as the engine answers:
  late, never lost.
- **No triggers of their own** for the end of a pause, Resume, an unlock, the
  PC waking or leaving full screen: the context that comes back starts its
  5 s, and the reload with them.

**What it means for alerts.**

- Plugged in, reload and warm-up take 2.3–3.7 + 0.3–0.5 = 2.6–4.2 s, inside
  the 5 s; the worst case measured, cold, leaves about 0.8 s.
- On battery, 2.8–3.2 s with the card awake; with the card already in D3 it is
  not measured, and deduced at 3.0–3.6 s.
- The first alert after a long rest comes a little earlier than in 0.2
  (deduced). The loaded engine at rest has its working set trimmed by Windows,
  and its first judgement takes 0.38–0.42 s plugged in, 0.63–0.92 s once the
  pages are out, 1.22 s on battery with the card in D3; after a reload the
  card is awake and the judgement warm, 0.4–0.5 s.

**Where it lives.**

- **`core` says only when the model will be needed soon**: a context waits
  for its 5 s and some of its judgements are not cached, or a statement must
  be written. It also says when nothing is in front. It does not know that the
  engine sleeps.
- **The client decides the rest.** The supervisor gets a new state, asleep: a
  live process without a model. To sleep it sends `shutdown` without closing
  stdin; to come back, `initialize`. This is already the engine's contract
  (`docs/design/engine.md`): after `shutdown` it has no model, as before
  `initialize`.
- After each command the worker wakes the engine if `core` asks, and puts it
  to sleep if nothing is in front. Each request of `core` starts the 5 minutes
  again: a deadline of the supervisor, like its restarts.
- **A wake is not a restart:** `core` does not judge the stable context again,
  and the records do not change.
- **The tray does not change:** an engine asleep shows as ready.

**The GPU's memory full at a wake.**

- **With a game open behind**, NVIDIA's driver, at its default (Sysmem
  Fallback), moves to shared memory what does not fit: the wake ends with
  slower judgements, about 2 s as under pressure in 0.2, not with an error.
  Nothing to change by hand.
- **If `initialize` refuses for the GPU's memory**, the engine stays asleep
  and tries again at the next need, not before 60 s. Until a wake succeeds,
  the tray shows 0.2's message on the card's memory, and Riprova tries at
  once. In 0.2 the engine stopped until Riprova.

**Every sleep and every wake is recorded**: when it slept and why, when it
was woken and by what, and when the model was ready after the warm-up. The
worker writes them to a table of the database, `engine_sleep`, added by
migration 0003 and kept 30 days like the evaluations, for the acceptance day
([ADR-0031](0031-acceptance-thresholds-v0-3.md)). A table rather than the
app's log, a technical choice made when the map closed, since
[#139](https://github.com/devfrx/jiffin/issues/139) had left it to the build:
the harness counts from a copy of the database
([ADR-0017](0017-evaluation-harness-subpackage.md)), and the log rolls over
at 1 MiB with four old files kept, so a busy day could lose its rows.

**Rejected.**

- **Deep sleep.** Too late: 4.1–6.0 s plugged in with the file partly cached,
  8.0–9.7 s cold, 4.7–8.0 s on battery, all beyond the 5 s. A small gain: 1.6
  W plugged in, nothing on battery where the card sleeps anyway, and about 0.1
  GiB of VRAM and 0.5 GiB of RAM more. The only return foreseeable with a
  margin, the end of a pause with a time, is not worth a second mechanism.
- **A spare process:** it saves only the start, and with the light sleep the
  process is already alive.
- **A watcher of the VRAM budget**, for apps in a window that want VRAM while
  Jiffin judges: not now. Games go to full screen, which is covered; after 5
  minutes without need the engine sleeps anyway; under pressure WDDM already
  moves the engine's memory, and judgements take about 2 s as in 0.2. A known
  limit: if needed, the way is DXGI's budget event in the engine
  (`RegisterVideoMemoryBudgetChangeNotificationEvent`).
- **"Prefer No Sysmem Fallback"** in NVIDIA's panel: with the fallback, a wake
  under pressure is slow; without it, it would fail.

**What this amends.**

- [ADR-0011](0011-engine-child-process-json-rpc.md): the light sleep; the
  wake with its warm-up; the 5 minutes; a call that wakes the engine and
  waits; the GPU's memory full at a wake no longer stops the engine.
- [ADR-0019](0019-five-second-debounce.md): the 5 s also hide the reload. A
  shorter debounce must stay above the return from the light sleep, 4.2 s
  with the warm-up.
- [ADR-0024](0024-hold-and-hide-alerts.md): while nothing is in front, the
  engine sleeps.
- [ADR-0013](0013-sqlite-storage.md) and
  [ADR-0014](0014-feedback-data-retention.md): the table `engine_sleep`,
  cleaned after 30 days.
- The VRAM threshold of [ADR-0003](0003-acceptance-thresholds.md), at most 4.0
  GiB, stays as it is.

## Consequences

**Positive**

- The GPU is free most of the day: asleep 57–68% of the time on the measured
  days, holding about 0.1 GiB.
- No alert later than in 0.2, and the first after a rest a little earlier.
- No new process, protocol method or dependency: `shutdown` and `initialize`
  already do it.

**Negative (accepted)**

- The supervisor has one state more, and a sleep deadline.
- A wake under a game is slow, about 2 s per judgement, as in 0.2 under
  pressure.
- The return on battery with the card in D3 is deduced, not measured.
- A window app that wants VRAM while Jiffin judges is not watched.

**Follow-up**

- The acceptance day of 0.3 counts late wakes and missed sleeps
  ([ADR-0031](0031-acceptance-thresholds-v0-3.md)).
- When this is built, `docs/design/` follows: `engine.md` (the state asleep in
  the supervision) and `pipeline.md` (when `core` asks for the model).
