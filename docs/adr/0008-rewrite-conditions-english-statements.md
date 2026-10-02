# ADR-0008: Rewrite conditions as English statements with the judge model

- **Status:** Accepted; amended by [ADR-0020](0020-read-the-time-in-core.md) (the rewriting gets the condition without its time)
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#22](https://github.com/devfrx/jiffin/issues/22) (translated conditions with Laya), [#14](https://github.com/devfrx/jiffin/issues/14) (pipeline) and [#26](https://github.com/devfrx/jiffin/issues/26) (rewriting measured)

## Context

Users write conditions in Italian, in the first person ("quando lavoro al
progetto Rossi"). The chosen judge in Q4_K_M loses more in Italian than in
English ([ADR-0006](0006-judge-rizzo-flow-q4.md)). Share of relevant pairs it
takes, judging all 9 reminders, with at most 0.1, 0.13 and 0.2 false alarms per
evaluated context, by how the condition reaches it:

| Condition given to the judge | ≤ 0.1 | ≤ 0.13 | ≤ 0.2 |
|---|---|---|---|
| The user's Italian text inside the question | — | — | 0.61 at best |
| Rewritten as a statement, in Italian | — | — | 0.76 at best |
| Translated to English, not rewritten | 0.75 | 0.79 | 0.87 |
| **Rewritten as a third-person English statement** | **0.81** | **0.88** | **0.91** |

(With Laya, English brought nothing: AUROC 0.807 against 0.803. The gain is
specific to the LLM judge.)

The sample's statements were written by hand. In the app something must write
them, once per reminder revision:

- **The judge's own model file, in text mode:** no extra weights or VRAM.
- **A translation model:** translates without rewriting (0.79 at ≤ 0.13); one
  more model in memory.
- **The base Spark-X2.5-4B:** kept the meaning 9 times out of 9, yet its
  statements gave the lowest recall (0.69 at ≤ 0.1), and it does not fit in
  VRAM next to the judge.

Measured with the same Q4_K_M file (llama.cpp, greedy decoding):

- Prompt v1, written before seeing any output: 7 of 9 statements keep the
  meaning. One negation was reversed; "lavoro a X" became "works at X", as if X
  were a company.
- Prompt v2, which adds two invented examples written after seeing those
  errors (so its score is optimistic): 8 of 9.
- AUROC unchanged: 0.986 with v2, as with the hand-written statements. Recall
  at ≤ 0.1 false alarms drops from 0.81 to 0.74–0.75, but on this sample that
  number has a 95% CI of [0.61, 0.93].
- The threshold does not transfer between rewritings: at d = 0.97, v2 takes
  0.86 with 0.142 false alarms per evaluated context; the hand-written
  statements 0.81 with 0.094.
- 0.2–0.4 s per reminder on the GPU, with the model already loaded.

## Decision

When a reminder is created or edited, the engine rewrites its condition
("Quando …") as one short English statement about the user, with the judge's
own GGUF in text mode:

- the chat template read from the GGUF, thinking disabled, greedy decoding
  (temperature 0), at most 64 tokens;
- prompt v2, below; the prompt lives in the engine, with a version
  ([ADR-0011](0011-engine-child-process-json-rpc.md));
- the statement is stored with the reminder's revision, together with the
  engine build that wrote it ([ADR-0013](0013-sqlite-storage.md)).

The judging threshold is fixed after this prompt is fixed, on the acceptance
day, and that day every statement of the active reminders is checked
([ADR-0003](0003-acceptance-thresholds.md)).

System prompt (v2):

```text
You rewrite the condition of a reminder as one short English statement about the user.
- The condition is written in Italian, in the first person, and starts with words like "quando" or "se".
- Write it in the third person, starting with "The user", as a fact that is true right now.
- Keep the names of apps, websites and projects exactly as written.
- Keep every negation and every "or".
- Do not add anything that is not in the condition.
- Reply with the statement only.
```

Examples, as user → assistant turns, all invented:

| Condition | Statement |
|---|---|
| quando apro Figma | The user has opened Figma. |
| se sono sul sito della banca | The user is on the bank's website. |
| se lavoro al progetto Rossi | The user is working on the Rossi project. |
| quando sto scrivendo una mail o una lettera | The user is writing an email or a letter. |
| se sto facendo qualcosa che non riguarda il lavoro | The user is doing something that is not related to work. |
| quando ascolto un podcast | The user is listening to a podcast. |
| se faccio altro che non sia studiare | The user is doing something other than studying. |
| se lavoro a Orione | The user is working on Orione. |

The last two are the v2 additions.

## Consequences

**Positive**

- Recall close to hand-written statements, with no extra model or VRAM.

**Negative (accepted)**

- A rewrite can change the meaning: 1 in 9 even with v2 ("working at X").
- Any change to this prompt moves the threshold.
- VRAM and time of rewriting inside the same session as judging are not
  measured: the measurement used a separate `llama-completion` process.

**Follow-up**

- `harness statements` lists every condition with its statement, for the
  check on the acceptance day
  ([ADR-0017](0017-evaluation-harness-subpackage.md)).
- Editing a reminder creates a new revision, so a wrong statement is fixed by
  editing the condition.
- Measured in the engine ([#37](https://github.com/devfrx/jiffin/issues/37)):
  a rewrite takes about 0.3 s, and judging and rewriting in one session peak
  at 3,257 MiB of VRAM, within the budget. The engine writes the prototype's
  statements word for word.
