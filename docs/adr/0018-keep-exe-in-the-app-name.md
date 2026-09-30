# ADR-0018: Keep `.exe` in the app name the judge sees

- **Status:** Accepted
- **Date:** 2026-10-01
- **Deciders:** devfrx
- **Sources:** ticket [#59](https://github.com/devfrx/jiffin/issues/59), with the measurement of the harness's `sample` ([#58](https://github.com/devfrx/jiffin/pull/58)); amends [ADR-0004](0004-context-identity.md)

## Context

[ADR-0004](0004-context-identity.md) normalized the app as the executable
name, lowercase, without `.exe`: `vivaldi.exe` became `vivaldi`. Ticket
[#11](https://github.com/devfrx/jiffin/issues/11) chose it by counting the
distinct contexts, not by measuring the judge. The prototype, with which the
threshold of [ADR-0007](0007-single-stage-pipeline.md) and the false-alarm
estimates of [ADR-0003](0003-acceptance-thresholds.md) were measured, sent
`vivaldi.exe`.

`python -m jiffin.harness sample` ran the prototype's labelled sample (106
contexts, 9 reminders) through the app's engine (engine 0.1.0, llama.cpp
b11081, judging prompt v1, rewriting prompt v2), changing one input at a
time:

| Contexts sent to the engine | AUROC | Recall with at most 0.1 / 0.13 / 0.2 false alarms per evaluated context | At d ≈ 0.97: recall | At d ≈ 0.97: false alarms per evaluated context |
|---|---|---|---|---|
| As the prototype sent them | 0.986 | 0.74 / 0.83 / 0.89 | 0.85 | 0.151 |
| Only the app name normalized | 0.979 | 0.54 / 0.67 / 0.80 | 0.83 | 0.226 |
| Only the title normalized | 0.986 | 0.75 / 0.84 / 0.90 | 0.85 | 0.142 |
| Only the address normalized | 0.986 | 0.75 / 0.81 / 0.90 | 0.86 | 0.151 |
| As ADR-0004 normalized them | 0.980 | 0.61 / 0.69 / 0.80 | 0.85 | 0.283 |
| **Normalized, with `.exe` kept** | **0.986** | **0.77 / 0.87 / 0.90** | **0.87** | **0.132** |

Normalizing titles and addresses costs nothing; the whole cost comes from
dropping `.exe`. At the starting threshold the false alarms double: with the
38 evaluations of the real day, about 11 a day instead of 5, against the cap
of 10 of ADR-0003, and before the doubling on the real day that ADR-0007
allows for. Why the judge needs the extension is not measured; one hypothesis
is that it recognizes a program better by the name of its file.

- **Keep `.exe`:** the judge sees the program as it did in the measurements.
  One rule still drives the debounce, the pair cache and "not here"; only the
  text of the key changes. Nothing is stored yet, so nothing to migrate.
- **Keep ADR-0004 as it is,** and let the acceptance day set the threshold, as
  ADR-0007 plans anyway: at equal false alarms the recall stays lower, 0.61
  instead of 0.77 with at most 0.1 per evaluated context.

## Decision

**The app is the executable name in lowercase, with its extension:**
`Vivaldi.exe` gives `vivaldi.exe`. The rest of ADR-0004 stands: the real
process for UWP apps, the normalization of title and address, and one
identity for the three mechanisms.

The supported browsers are named the same way: `vivaldi.exe`, `chrome.exe`
and `brave.exe`.

## Consequences

**Positive**

- On the sample, the false alarms at the starting threshold halve, and the
  recall at equal false alarms rises.
- The judge sees what it saw when the threshold was chosen.

**Negative (accepted)**

- The key carries an extension that tells no two programs apart, and the
  judge reads four more characters per evaluation.

**Follow-up**

- The unit tests of `core` pin the rule with examples.
- The acceptance day measures the real rate
  ([ADR-0003](0003-acceptance-thresholds.md)).
