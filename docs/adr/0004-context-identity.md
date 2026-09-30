# ADR-0004: Define a context as app, window title and tab address

- **Status:** Accepted
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** tickets [#11](https://github.com/devfrx/jiffin/issues/11) (context), [#15](https://github.com/devfrx/jiffin/issues/15) (cache expiry) and [#17](https://github.com/devfrx/jiffin/issues/17) (tab address)

## Context

One notion of "context" serves three mechanisms that must agree:

- the **debounce**: a context is evaluated only once it has been stable for a
  while;
- the **pair cache** (context, reminder);
- the **"not here"** answer, which silences a reminder "here".

Titles are short and ambiguous. They change while the work does not (an editor
switching files), and repeat across unrelated work ("New tab"). Chrome shows a
shortened address (no `https://`, no `www.`); Vivaldi and Brave show the full
one.

Candidate identity rules, measured on the working day of 2026-09-28 (distinct
contexts evaluated with a 20 s debounce and the cache):

| Rule | Evaluations |
|---|---|
| Exact raw app, title and address | 38 |
| **Normalized app, title and address** | **37** |
| App and site in browsers, app and title elsewhere | 27 |
| App only | 11 |

## Decision

**Signals**, read from the foreground window:

- **app**: the executable name, lowercase, without `.exe`; for UWP apps the
  real process, not `ApplicationFrameHost`;
- **title**: the window title;
- **address**: only in Vivaldi, Chrome and Brave, the text of the address bar
  ([ADR-0005](0005-browser-address-ui-automation.md)).

**Not contexts:** private and incognito windows, which are ignored entirely
(no evaluation, no alert, nothing stored), and Jiffin's own windows.

**Normalization.**

- Title: strip the browser suffix (` - Vivaldi`, ` - Google Chrome`,
  ` - Brave`), a leading counter (`(3) `) and unsaved-file markers (`●`, `*`)
  at the start or the end.
- Address: strip the scheme, `www.`, everything from `?` or `#` on, and a
  trailing `/`. Chrome's shortened text then gives the same key as the full
  address of Vivaldi and Brave, and dropping the query also drops searches and
  tokens.
- When the address cannot be read (bar not found, an error, the user typing in
  the bar), the context is app and title.

**Identity.** Two contexts are the same when app, normalized title and
normalized address are all equal. The same rule drives the three mechanisms:

- **Debounce:** the context is stable while its key does not change for the
  debounce interval, 20 s ([ADR-0007](0007-single-stage-pipeline.md)).
- **Pair cache:** the key is exactly the text the model sees, so a cached
  score is the one the model would give again. It is invalidated only by a new
  revision of the reminder or a different engine build
  ([ADR-0013](0013-sqlite-storage.md)). Entries unused for 30 days are deleted
  for privacy ([ADR-0014](0014-feedback-data-retention.md)).
- **"Not here":** silences the reminder only in that context — that page, or
  that window with that title — not on the whole site or in the whole app. It
  lasts as long as the reminder exists, and resets when the reminder's text
  changes.

A narrow "not here" is deliberate: if it silenced the whole site, a relevant
reminder on another page of that site would never arrive, and nobody would
notice. A repeated alert is visible; a missed one is not.

A per-site key would save about a quarter of the evaluations, but with the
same key the judge would give different pages the same answer.

## Consequences

**Positive**

- One rule for three mechanisms, so they cannot disagree.
- Cached scores are exact, so the cache never needs to expire for
  correctness.

**Negative (accepted)**

- The same title in different work gets the same answer: the judge has
  nothing else to tell them apart.
- Every new title is a new context; the debounce and the cache bound the cost.
- Short, ambiguous titles are left to the judge, and the acceptance day
  measures how it copes ([ADR-0003](0003-acceptance-thresholds.md)).

**Follow-up**

- Unit tests in `core` pin the normalization with examples.
