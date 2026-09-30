# Jiffin

Contextual reminders for Windows 11. You write a reminder with a condition in
plain Italian — *quando lavoro al progetto Rossi, ricordami di aggiornare il
changelog* — and Jiffin shows it in an overlay when your current work (the
active app, the window title, the address of the browser tab) makes the
condition true. A local language model evaluates every condition on your
machine; nothing leaves it.

## Status

The design is settled and implementation is starting.

- Why things are the way they are: [architecture decision records](docs/adr/README.md).
- What is being built for the first installable version: the
  [v0.1.0 milestone](https://github.com/devfrx/jiffin/milestone/1).

## Development

Python and every tool come from [uv](https://docs.astral.sh/uv/), at the
versions in `uv.lock`:

```sh
uv sync                               # Python 3.13 and all dependencies
uv run pre-commit install             # run the quality gates on every commit
uv run pre-commit run --all-files     # run them on the whole repository
uv run pytest                         # unit tests
uv run scripts/fetch_llama_cpp.py     # llama.cpp for the engine, about 575 MB, once
uv run pytest -m integration          # tests that need the model and the GPU
```

## License

[Apache-2.0](LICENSE).
