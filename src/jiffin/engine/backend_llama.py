# Derived from Rizzo Flow, src/rizzo_flow/backend_llama.py at commit b9ba007e
# (https://github.com/Rizzo-AI-Academy/rizzo-flow). Copyright 2026 Simone Rizzo — Rizzo AI
# Academy. Licensed under the Apache License, Version 2.0.
# Changed for Jiffin: loads with the engine settings of ADR-0011 and reports what `initialize`
# returns; scores with the shared prefix only; judging (d = logit A − logit B) and greedy
# generation for rewriting added.
"""llama.cpp on one session: scoring in flat unpadded batches, with prefix branches that share
KV cells, and greedy generation."""

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NoReturn, Self

from jinja2 import TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from jiffin.engine import llama_release, prompts
from jiffin.engine.errors import ModelNotLoadable, TextTooLong
from jiffin.engine.llama_cpp import Session
from jiffin.protocol.messages import Context, EngineSettings, Statement

N_BATCH = 2048  # most tokens handed to one llama_decode call
PREFILL_CHUNK = 512  # llama.cpp splits each call into micro-batches of this many tokens
ARCHITECTURE = "spark2_5"


class LlamaTokenizer:
    """The two calls the prompts make, served by the GGUF itself: its chat template rendered
    the way transformers renders it, and its vocabulary for encoding."""

    def __init__(self, session: Session, template: str) -> None:
        def raise_exception(message: str) -> NoReturn:
            raise ValueError(message)

        environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        environment.globals["raise_exception"] = raise_exception
        self.template = environment.from_string(template)
        self.session = session

    def apply_chat_template(self, messages: list[dict[str, str]], **variables: object) -> str:
        return self.template.render(messages=messages, **variables)

    def encode(self, text: str) -> list[int]:
        return self.session.tokenize(text)


class LlamaBackend:
    def __init__(
        self, session: Session, tokenizer: prompts.Tokenizer, settings: EngineSettings
    ) -> None:
        self.session = session
        self.tokenizer = tokenizer
        self.settings = settings

    @classmethod
    def load(cls, path: Path, settings: EngineSettings) -> Self:
        if not path.is_file():
            raise ModelNotLoadable(f"there is no model file at {path}")
        try:
            # The longest question is `context_per_question` tokens; a micro-batch adds at most
            # N_BATCH suffix tokens on top of the prefix they share, so this many cells suffice.
            session = Session.load(
                path,
                directory=llama_release.locate(),
                n_ctx=settings.context_per_question + N_BATCH,
                n_batch=N_BATCH,
                n_ubatch=PREFILL_CHUNK,
                n_seq_max=settings.micro_batch + 1,
                load_mode=settings.load_mode,
                kv_type=settings.kv_cache,
            )
        except OSError as error:  # the runtime is missing, or one of its libraries
            raise ModelNotLoadable(str(error)) from error
        try:
            architecture = session.meta("general.architecture")
            if architecture != ARCHITECTURE:
                raise ModelNotLoadable(
                    f"only the {ARCHITECTURE} architecture is supported, not {architecture}"
                )
            template = session.chat_template()
            if not template:
                raise ModelNotLoadable("the model file carries no chat template")
            try:
                tokenizer = LlamaTokenizer(session, template)
            except TemplateError as error:
                raise ModelNotLoadable(f"the chat template cannot be read: {error}") from error
        except Exception:
            session.close()
            raise
        return cls(session, tokenizer, settings)

    @property
    def gpu(self) -> str:
        return self.session.device.description

    @property
    def model_type(self) -> str:
        return self.session.description()

    def free_vram_bytes(self) -> int:
        return self.session.free_bytes()

    def close(self) -> None:
        """Release the context and the weights."""
        self.session.close()

    def judge(self, context: Context, statements: Sequence[Statement]) -> dict[int, float]:
        """d = logit("yes") − logit("no") for every statement, by id (ADR-0006)."""
        prefix, jobs = prompts.compile_judge(
            self.tokenizer, context, statements, self.settings.context_per_question
        )
        logits = self.score(prefix, jobs)
        return {key: yes - no for key, (yes, no) in logits.items()}

    def rewrite(self, condition: str) -> str:
        """The condition as one English statement, decoded greedily (ADR-0008)."""
        prompt = prompts.compile_rewrite(
            self.tokenizer, condition, self.settings.context_per_question
        )
        statement = self.session.detokenize(self.generate(prompt, prompts.STATEMENT_TOKENS))
        if not statement.strip():
            raise RuntimeError("the model wrote an empty statement")
        return statement.strip()

    def generate(self, prompt: list[int], limit: int) -> list[int]:
        """The tokens that greedily follow `prompt`, up to the end of the generation.

        Raise TextTooLong when the generation goes on past `limit` tokens: text is never cut.
        """
        session = self.session
        session.clear()
        row = self._feed(prompt, 0, 0, logits=True)
        generated: list[int] = []
        while not session.is_end(token := session.sample(row)):
            if len(generated) == limit:
                raise TextTooLong(f"the statement did not end within {limit} tokens")
            generated.append(token)
            session.decode([token], [len(prompt) + len(generated) - 1], [0], [0])
            row = 0
        return generated

    def score(self, prefix: list[int], jobs: list[prompts.Compiled]) -> dict[int, list[float]]:
        """The logits of every question's answer slots, by id."""
        if not jobs:
            raise ValueError("No questions supplied")
        if any(
            job.tokens[: len(prefix)] != prefix or len(job.tokens) <= len(prefix) for job in jobs
        ):
            raise ValueError("Invalid shared prefix")
        session = self.session
        result = {}
        # A lone question has nobody to share the prefix with: one pass is the same computation
        # and saves a call, which is a third of the latency of a short request.
        if not prefix or len(jobs) == 1:
            for job in jobs:
                session.clear()
                row = self._feed(job.tokens, 0, 0, logits=True)
                result[job.id] = session.logits(row, job.slots)
        else:
            session.clear()
            self._feed(prefix, 0, 0, logits=False)
            start = len(prefix)
            for group in self._groups(sorted(jobs, key=lambda j: len(j.tokens)), start):
                # Branches reference the prefix cells of sequence 0; nothing is copied, and
                # dropping a branch leaves the prefix untouched for the next micro-batch.
                for sequence in range(1, len(group) + 1):
                    session.branch(0, sequence)
                suffixes = [job.tokens[start:] for job in group]
                if len(group) == 1:
                    rows = [self._feed(suffixes[0], start, 1, logits=True)]  # any length
                else:
                    # Suffixes lie end to end: no padding, each reads its own last position.
                    tokens: list[int] = []
                    positions: list[int] = []
                    sequences: list[int] = []
                    rows = []
                    for sequence, suffix in enumerate(suffixes, start=1):
                        tokens += suffix
                        positions += range(start, start + len(suffix))
                        sequences += [sequence] * len(suffix)
                        rows.append(len(tokens) - 1)
                    session.decode(tokens, positions, sequences, rows)
                for job, row in zip(group, rows, strict=True):
                    result[job.id] = session.logits(row, job.slots)
                for sequence in range(1, len(group) + 1):
                    session.drop(sequence)
        session.synchronize()
        return result

    def _feed(self, tokens: list[int], start: int, sequence: int, *, logits: bool) -> int:
        """Run `tokens` on one sequence, N_BATCH per call; the batch row of the final logits.
        llama.cpp splits each call into PREFILL_CHUNK micro-batches on its own."""
        row = 0
        for offset in range(0, len(tokens), N_BATCH):
            piece = tokens[offset : offset + N_BATCH]
            final = logits and offset + len(piece) == len(tokens)
            self.session.decode(
                piece,
                range(start + offset, start + offset + len(piece)),
                [sequence] * len(piece),
                [len(piece) - 1] if final else (),
            )
            row = len(piece) - 1
        return row

    def _groups(
        self, jobs: list[prompts.Compiled], prefix_length: int
    ) -> Iterator[list[prompts.Compiled]]:
        """Micro-batches of up to `micro_batch` suffixes that fit one llama_decode call."""
        group: list[prompts.Compiled] = []
        used = 0
        for job in jobs:
            size = len(job.tokens) - prefix_length
            if group and (len(group) == self.settings.micro_batch or used + size > N_BATCH):
                yield group
                group, used = [], 0
            group.append(job)
            used += size
        if group:
            yield group
