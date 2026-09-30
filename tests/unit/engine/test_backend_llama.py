from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import cast

import pytest

from jiffin.engine.backend_llama import N_BATCH, LlamaBackend
from jiffin.engine.errors import TextTooLong
from jiffin.engine.llama_cpp import Session
from jiffin.engine.prompts import Compiled
from jiffin.protocol.messages import Context, EngineSettings, Statement

SLOTS = [65, 66]
END = 0


@dataclass
class Decoded:
    tokens: list[int]
    positions: list[int]
    sequences: list[int]
    outputs: list[int]


@dataclass
class FakeSession:
    """Records every call; the logits at a row are its token and the token's negation."""

    calls: list[object] = field(default_factory=list)
    batch: list[int] = field(default_factory=list)
    script: list[int] = field(default_factory=list)
    """The tokens `sample` returns, in order; END ends a generation."""

    def clear(self) -> None:
        self.calls.append("clear")

    def decode(
        self,
        tokens: Sequence[int],
        positions: Sequence[int],
        sequences: Sequence[int],
        outputs: Iterable[int] = (),
    ) -> None:
        assert 0 < len(tokens) <= N_BATCH
        self.batch = list(tokens)
        self.calls.append(Decoded(list(tokens), list(positions), list(sequences), list(outputs)))

    def logits(self, index: int, slots: list[int]) -> list[float]:
        assert slots == SLOTS
        return [float(self.batch[index]), float(-self.batch[index])]

    def sample(self, index: int) -> int:
        assert index == len(self.batch) - 1
        self.calls.append(("sample", index))
        return self.script.pop(0)

    def is_end(self, token: int) -> bool:
        return token == END

    def detokenize(self, tokens: Sequence[int]) -> str:
        return "".join(map(chr, tokens))

    def branch(self, source: int, target: int) -> None:
        self.calls.append(("branch", source, target))

    def drop(self, sequence: int) -> None:
        self.calls.append(("drop", sequence))

    def synchronize(self) -> None:
        self.calls.append("synchronize")


class Tokenizer:
    """One token per character; the chat template joins the messages."""

    def apply_chat_template(self, messages: list[dict[str, str]], **variables: object) -> str:
        return "".join(message["content"] for message in messages)

    def encode(self, text: str) -> list[int]:
        return [ord(character) for character in text]


def backend(session: FakeSession, micro_batch: int = 16) -> LlamaBackend:
    settings = EngineSettings(
        context_per_question=2048, micro_batch=micro_batch, load_mode="direct_io", kv_cache="f16"
    )
    return LlamaBackend(cast(Session, session), tokenizer=Tokenizer(), settings=settings)


def job(key: int, suffix: list[int]) -> Compiled:
    return Compiled(key, [1, 2, 3, *suffix], SLOTS)


def test_the_prefix_is_decoded_once_and_every_suffix_branches_from_it() -> None:
    session = FakeSession()
    logits = backend(session).score([1, 2, 3], [job(7, [70, 71]), job(8, [80])])
    assert logits == {7: [71.0, -71.0], 8: [80.0, -80.0]}
    assert session.calls == [
        "clear",
        Decoded([1, 2, 3], [0, 1, 2], [0, 0, 0], []),
        ("branch", 0, 1),
        ("branch", 0, 2),
        # Shortest first, end to end, each suffix on its own sequence after the prefix.
        Decoded([80, 70, 71], [3, 3, 4], [1, 2, 2], [0, 2]),
        ("drop", 1),
        ("drop", 2),
        "synchronize",
    ]


def test_micro_batches_hold_at_most_micro_batch_questions() -> None:
    session = FakeSession()
    jobs = [job(key, [100 + key]) for key in range(5)]
    logits = backend(session, micro_batch=2).score([1, 2, 3], jobs)
    assert logits == {key: [100.0 + key, -100.0 - key] for key in range(5)}
    decoded = [call for call in session.calls if isinstance(call, Decoded)]
    assert [len(call.outputs) for call in decoded] == [0, 2, 2, 1]


def test_a_micro_batch_never_hands_llama_cpp_more_than_n_batch_tokens() -> None:
    session = FakeSession()
    long = N_BATCH // 2 + 1
    jobs = [job(1, [11] * long), job(2, [12] * long)]
    backend(session).score([1, 2, 3], jobs)
    decoded = [call for call in session.calls if isinstance(call, Decoded)]
    assert [len(call.tokens) for call in decoded] == [3, long, long]
    assert decoded[2].sequences == [1] * long


def test_a_lone_question_is_decoded_in_one_pass() -> None:
    session = FakeSession()
    logits = backend(session).score([1, 2, 3], [job(4, [40, 41])])
    assert logits == {4: [41.0, -41.0]}
    assert session.calls == [
        "clear",
        Decoded([1, 2, 3, 40, 41], [0, 1, 2, 3, 4], [0] * 5, [4]),
        "synchronize",
    ]


def test_a_question_that_does_not_start_with_the_prefix_is_refused() -> None:
    with pytest.raises(ValueError, match="Invalid shared prefix"):
        backend(FakeSession()).score([1, 2, 3], [Compiled(1, [1, 2, 9, 4], SLOTS)])


def test_judging_gives_d_as_the_logit_of_yes_minus_the_logit_of_no() -> None:
    context = Context(app="figma", title="Icone – Figma", address=None)
    statements = [Statement(id=3, text="The user is in Figma."), Statement(id=9, text="No.")]
    d = backend(FakeSession()).judge(context, statements)
    # Every question ends with the full stop of its closing line, and the fake's logits at a
    # token t are (t, −t): d = 2t.
    assert d == {3: 2.0 * ord("."), 9: 2.0 * ord(".")}


def test_generation_is_greedy_until_the_end_of_the_generation() -> None:
    session = FakeSession(script=[72, 105, END])
    assert backend(session).generate([1, 2, 3], limit=64) == [72, 105]
    assert session.calls == [
        "clear",
        Decoded([1, 2, 3], [0, 1, 2], [0, 0, 0], [2]),
        ("sample", 2),
        Decoded([72], [3], [0], [0]),
        ("sample", 0),
        Decoded([105], [4], [0], [0]),
        ("sample", 0),
    ]


def test_a_generation_may_take_exactly_the_limit() -> None:
    assert backend(FakeSession(script=[72, 105, END])).generate([1, 2, 3], limit=2) == [72, 105]


def test_a_generation_longer_than_the_limit_is_refused_not_cut() -> None:
    with pytest.raises(TextTooLong, match="within 2 tokens"):
        backend(FakeSession(script=[72, 105, 33, END])).generate([1, 2, 3], limit=2)


def test_rewrite_returns_the_statement_without_surrounding_space() -> None:
    session = FakeSession(script=[*map(ord, " The user has opened Figma.\n"), END])
    assert backend(session).rewrite("quando apro Figma") == "The user has opened Figma."


def test_an_empty_statement_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="empty statement"):
        backend(FakeSession(script=[ord(" "), END])).rewrite("quando apro Figma")
