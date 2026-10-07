# ADR-0002: License the code under Apache-2.0 and write the repository in English

- **Status:** Accepted; amended by [ADR-0026](0026-italian-in-language-files.md) (the app's Italian lives in language files, and a check keeps it there)
- **Date:** 2026-09-29
- **Deciders:** devfrx
- **Sources:** ticket [#8](https://github.com/devfrx/jiffin/issues/8) (language and license)

## Context

The repository is private for now, but may be published. The owner writes in
Italian; libraries, error messages and Conventional Commits prefixes are in
English.

What the project builds on is permissively licensed (checked on 2026-09-29 on
the model cards and repositories): Rizzo Flow (LoRA and code), its base model
Spark-X2.5-4B and Laya are Apache-2.0; llama.cpp and harrier-oss-v1-270m are
MIT. The UI toolkit was still open when this was decided: PyQt6 6.11.0 is
`GPL-3.0-only`, while PySide6 6.11.2 is
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` (PyPI).

## Decision

**License: Apache-2.0.** It is the license of the models and code the project
derives from; it allows use in closed products, requires attribution and grants
patent rights explicitly. It applies from the moment the code is published or
distributed.

- `LICENSE` at the root; a `NOTICE` file when derived code or a dependency
  requires one, as the engine derived from Rizzo Flow may
  ([ADR-0011](0011-engine-child-process-json-rpc.md)).
- No GPL-only dependencies. PyQt6 is excluded; PySide6 is used under the LGPL,
  dynamically linked, which is the normal case in Python.

**Language.**

| What | Language |
|---|---|
| Code: identifiers and comments | English |
| Repository docs: README, ADRs, design docs, mockups | English |
| Commit messages (Conventional Commits) and changelog | English |
| Implementation issues and pull requests | English |
| User interface | Italian, with all strings in one place |
| Decision map and its tickets | Italian |

One language makes the repository read as a whole, and keeps it readable by
anyone if it becomes public.

## Consequences

**Positive**

- A license compatible with everything used so far.
- The repository reads in one language.

**Negative (accepted)**

- Decisions were taken in Italian on the map; the ADRs are translations, not
  copies, and the two can drift. The ADRs are the reference for the code.

**Follow-up**

- Check the license of every new dependency when it is added.
- The measurement prototype (`NO_GIT\sibyl-misura`) mixes Italian and English
  and stays outside the repository. Any part of it that moves in, such as the
  evaluation harness, is rewritten in English.
