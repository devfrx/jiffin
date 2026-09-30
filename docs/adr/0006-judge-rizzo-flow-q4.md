# ADR-0006: Judge conditions with Rizzo Flow 4B in Q4_K_M

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#13](https://github.com/devfrx/jiffin/issues/13) (Laya measured), [#19](https://github.com/devfrx/jiffin/issues/19) and [#21](https://github.com/devfrx/jiffin/issues/21) (alternatives researched), [#20](https://github.com/devfrx/jiffin/issues/20) (alternatives measured), [#23](https://github.com/devfrx/jiffin/issues/23) (CLM-8B), [#24](https://github.com/devfrx/jiffin/issues/24) (Q4_K_M measured), [#9](https://github.com/devfrx/jiffin/issues/9) and [#14](https://github.com/devfrx/jiffin/issues/14) (decision)

## Context

For every reminder, something must answer "is this condition true in this
context?" — for conditions written in Italian, locally
([ADR-0001](0001-keep-data-and-inference-local.md)), in at most 4.0 GiB of
VRAM ([ADR-0003](0003-acceptance-thresholds.md)).

Candidates were measured on a sample of 106 real contexts and 9 reminders
(954 pairs, 178 relevant; labels LLM-assisted). AUROC at each candidate's best
question format (the two Rizzo Flow rows at the same format, to compare like
with like), on all conditions and on the two hard classes; "pipeline" is the
share of relevant pairs taken with at most 0.2 false alarms per evaluated
context, after a top-5 embedding retrieval:

| Candidate | AUROC | Italian only | Vague | Negation | Pipeline | VRAM |
|---|---|---|---|---|---|---|
| Laya, without training | 0.807 | 0.803 | 0.64 | 0.46 | 0.33 | 2.4 GB |
| Qwen3-Reranker-0.6B | 0.694 | 0.694 | 0.68 | 0.15 | — | — |
| bge-m3-zeroshot-v2.0-c (NLI) | 0.890 | 0.890 | 0.52 | 0.41 | 0.25 | 2.2 GB |
| Qwen3.5-2B as a judge | 0.977 | 0.886 | 0.79 | 0.37 | 0.70 | 3.8 GB |
| Spark-X2.5-4B, base | 0.978 | 0.978 | 0.80 | 0.54 | 0.78 | — |
| Rizzo Flow 4B, Q8_0 | 0.988 | 0.979 | 0.87 | 0.84 | 0.83 | 5.7 GiB |
| **Rizzo Flow 4B, Q4_K_M** | **0.985** | **0.969** | **0.84** | **0.82** | **0.83** | **4.0 GiB** |

Rizzo Flow 4B is Spark-X2.5-4B with a LoRA for decisions merged into the
weights, both Apache-2.0: an LLM whose logits for two answer options are read.
Of the 72 projects listed in awesome-jev, it was the one worth measuring: trained
for decisions, on a multilingual base, and tested on Windows. CLM-8B was
rejected: its yes/no is an uncalibrated softmax between two texts, its encoder
takes 5.4 GiB even in Q5_K_M, it was released in alpha on 2026-09-23 and has no
evidence on Italian.

Q4_K_M against Q8_0: in English the loss is small (−0.003, 95% CI
[−0.006, −0.001]) and the pipeline share is unchanged (0.83); in Italian the
loss is larger (−0.010) and the pipeline share drops from 0.80 to 0.67. At the
question format finally chosen, `json / en / f2 / sa`, the Q4_K_M reaches
0.986 (0.985 when the format is chosen on half the contexts and measured on the
other half). On the GPU an event takes 75 ms with one candidate and 188 ms with
five; on the CPU the model is unusable (8.7–20.7 s per event, measured in
Q8_0).

## Decision

- The judge is **Rizzo Flow 4B, trained, in Q4_K_M**, run by llama.cpp on the
  NVIDIA GPU with CUDA ([ADR-0011](0011-engine-child-process-json-rpc.md)).
- The score is **d = logit("yes") − logit("no")** for the two answer options.
- The question format is `json / en / f2 / sa`: the context state as JSON, the
  condition as an English statement
  ([ADR-0008](0008-rewrite-conditions-english-statements.md)), two options
  with "yes" in A.
- Everything is pinned:
  - weights: `rizzoaiacademy/rizzo-flow` at revision
    `55633c8cbd2b826bd3eefdeb05310450996649df`, file
    `spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf`, 2,600,224,416 bytes, sha256
    `79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54`;
  - Rizzo Flow code at commit `b9ba007e`;
  - llama.cpp build b11081.
- A change of model, prompt or llama.cpp build ships only after it is measured
  again ([ADR-0017](0017-evaluation-harness-subpackage.md)).

It is the most accurate candidate, including on vague conditions and on
negation, where the others fail. Q8_0 does not fit the VRAM budget; Q4_K_M
does, and its weakness in Italian is avoided by asking in English.

## Consequences

**Positive**

- Accuracy far above the candidates that need no training.
- One model file both judges and rewrites conditions
  ([ADR-0008](0008-rewrite-conditions-english-statements.md)).

**Negative (accepted)**

- An NVIDIA GPU is required.
- The ecosystem was one week old at decision time, with a single maintainer
  and no tags or releases: hence the pinning and an engine of our own
  ([ADR-0011](0011-engine-child-process-json-rpc.md)).
- The sample is small (vague conditions and negation have one reminder each),
  and its labels are LLM-assisted.

**Follow-up**

- The acceptance day ([ADR-0003](0003-acceptance-thresholds.md)) is where the
  judge meets the owner's own judgement at scale.
- Rizzo Flow 1.7B exists and was not measured; its authors call it much less
  accurate, and with a single stage the VRAM does not require it.
