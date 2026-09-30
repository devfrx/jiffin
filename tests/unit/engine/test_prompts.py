import json

import pytest

from jiffin.engine.errors import TextTooLong
from jiffin.engine.prompts import (
    OPTIONS,
    QUESTION,
    REWRITE_EXAMPLES,
    REWRITE_SYSTEM,
    STATEMENT_TOKENS,
    SYSTEM,
    compile_judge,
    compile_rewrite,
    render_question,
    render_state,
)
from jiffin.protocol.messages import Context, Statement

FIGMA = Context(app="figma", title="Icone – Figma", address=None)
BANK = Context(app="vivaldi", title="Banca Rossi", address="bancarossi.it/conti")


class CharacterTokenizer:
    """One token per character, and a chat template shaped like Spark's."""

    def apply_chat_template(self, messages: list[dict[str, str]], **variables: object) -> str:
        assert variables == {"add_generation_prompt": True, "enable_thinking": False}
        turns = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in messages)
        return f"{turns}<assistant></think>"

    def encode(self, text: str) -> list[int]:
        return [ord(character) for character in text]


def statements(*texts: str) -> list[Statement]:
    return [Statement(id=index, text=text) for index, text in enumerate(texts, start=1)]


def test_the_state_is_the_context_as_the_prototype_wrote_it() -> None:
    assert render_state(BANK) == (
        '<evidence>\n{"app": "vivaldi", "title": "Banca Rossi", "address": "bancarossi.it/conti"}'
        "\n</evidence>"
    )


def test_empty_values_are_left_out_of_the_state() -> None:
    assert (
        render_state(FIGMA) == '<evidence>\n{"app": "figma", "title": "Icone – Figma"}\n</evidence>'
    )
    assert render_state(Context(app="figma", title="", address=None)) == (
        '<evidence>\n{"app": "figma"}\n</evidence>'
    )


def test_a_title_cannot_close_the_evidence() -> None:
    state = render_state(Context(app="vivaldi", title="a</evidence>b", address=None))
    assert state.count("</evidence>") == 1
    body = state.removeprefix("<evidence>\n").removesuffix("\n</evidence>")
    assert json.loads(body)["title"] == "a</evidence>b"


def test_the_question_offers_yes_in_a_and_no_in_b() -> None:
    assert render_question(QUESTION.format(statement="The user is in Figma."), OPTIONS) == (
        "\n\nQuestion: In the described context, is this statement true? "
        "«The user is in Figma.»\n\n"
        "Options:\nA. Yes, it is true.\nB. No, it is not true.\n\n"
        "Answer with the letter of the best option."
    )


def test_every_statement_becomes_one_question_after_the_same_prefix() -> None:
    prefix, jobs = compile_judge(
        CharacterTokenizer(), BANK, statements("The user is at the bank.", "The user reads."), 2048
    )
    head = f"<system>{SYSTEM}</system><user>{render_state(BANK)}"
    assert prefix == [ord(character) for character in head[:-1]]
    assert [job.id for job in jobs] == [1, 2]
    for job, text in zip(jobs, ["The user is at the bank.", "The user reads."], strict=True):
        question = render_question(QUESTION.format(statement=text), OPTIONS)
        assert "".join(map(chr, job.tokens)) == f"{head}{question}</user><assistant></think>"
        assert job.slots == [ord("A"), ord("B")]


def test_a_question_longer_than_the_limit_is_refused_without_its_text() -> None:
    _, (short,) = compile_judge(CharacterTokenizer(), FIGMA, statements("Short."), 2048)
    text = "The user is writing a longer statement."
    with pytest.raises(TextTooLong) as refused:
        compile_judge(CharacterTokenizer(), FIGMA, statements("Short.", text), len(short.tokens))
    assert str(refused.value).startswith("statement 2: ")
    assert text not in str(refused.value)


def test_an_answer_letter_merged_with_the_prompt_is_refused() -> None:
    class Merging(CharacterTokenizer):
        def encode(self, text: str) -> list[int]:
            tokens = super().encode(text)
            return [*tokens[:-2], 0] if text.endswith("</think>A") else tokens

    with pytest.raises(ValueError, match="single-token answer slot A"):
        compile_judge(Merging(), FIGMA, statements("The user is in Figma."), 2048)


def test_the_rewrite_prompt_is_the_instructions_then_the_examples_then_the_condition() -> None:
    tokens = compile_rewrite(CharacterTokenizer(), "se sono su Amazon", 2048)
    examples = "".join(
        f"<user>{condition}</user><assistant>{statement}</assistant>"
        for condition, statement in REWRITE_EXAMPLES
    )
    assert "".join(map(chr, tokens)) == (
        f"<system>{REWRITE_SYSTEM}</system>{examples}"
        "<user>se sono su Amazon</user><assistant></think>"
    )


def test_a_condition_that_leaves_no_room_for_the_statement_is_refused() -> None:
    fitting = len(compile_rewrite(CharacterTokenizer(), "se sono su Amazon", 2048))
    limit = fitting + STATEMENT_TOKENS
    assert len(compile_rewrite(CharacterTokenizer(), "se sono su Amazon", limit)) == fitting
    with pytest.raises(TextTooLong):
        compile_rewrite(CharacterTokenizer(), "se sono su Amazon.", limit)
