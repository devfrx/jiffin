import json
from datetime import date
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.records import ContextAnswer, Here, Revision
from jiffin.core.situations import Ends, Situation
from jiffin.harness import labels
from jiffin.harness.day import Day, Pair, key
from jiffin.harness.errors import HarnessError

DAY = date(2026, 10, 5)
T0 = 1_791_190_800_000  # 2026-10-05 09:00 UTC
ICONS = Revision(10, 1, 1, "quando apro Figma", "esportare le icone", "quando apro Figma")
CONTEXTS = (
    Context("figma.exe", "Icone - Figma", None),
    Context("vivaldi.exe", "Banca Rossi", "bancarossi.it"),
    Context("outlook.exe", "Posta in arrivo", None),
)
PAIRS = {pair.key: pair for pair in (Pair(context, ICONS) for context in CONTEXTS)}
FIGMA, BANK, MAIL = PAIRS


def test_the_pairs_are_written_with_their_texts(tmp_path: Path) -> None:
    path = labels.path_for(tmp_path, DAY)
    labels.prepare(PAIRS, path, DAY)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "labels-2026-10-05.json"
    assert record["pairs"][1] == {
        "key": BANK,
        "app": "vivaldi.exe",
        "title": "Banca Rossi",
        "address": "bancarossi.it",
        "remainder": "quando apro Figma",
        "action": "esportare le icone",
    }
    assert (record["claude"], record["uncertain"], record["owner"]) == ({}, [], {})
    assert "condition without its time" in record["instructions"]


def test_preparing_again_keeps_every_label(tmp_path: Path) -> None:
    path = labels.path_for(tmp_path, DAY)
    labelled = labels.prepare(PAIRS, path, DAY)
    labelled.claude = {FIGMA: True, BANK: False}
    labelled.uncertain = [BANK]
    labelled.save()
    labelled.answer(BANK, True)
    again = labels.prepare(dict(list(PAIRS.items())[:1]), path, DAY)
    assert [pair["key"] for pair in again.pairs] == [FIGMA]
    assert (again.claude, again.uncertain, again.owner) == (
        {FIGMA: True, BANK: False},
        [BANK],
        {BANK: True},
    )


def test_the_owner_wins_and_agreement_is_counted_where_both_labelled(tmp_path: Path) -> None:
    labelled = labels.Labels(
        tmp_path / "labels.json", DAY, [], {FIGMA: True, BANK: False}, [], {BANK: True, MAIL: False}
    )
    assert labelled.final() == {FIGMA: True, BANK: True, MAIL: False}
    assert labelled.agreement() == (0, 1)


def test_remind_here_counts_under_the_owners_page_and_over_claude(tmp_path: Path) -> None:
    labelled = labels.Labels(
        tmp_path / "labels.json", DAY, [], {FIGMA: False, BANK: False}, [], {BANK: False}
    )
    asked = {FIGMA: True, BANK: True}
    assert labelled.final(asked) == {FIGMA: True, BANK: False}


def test_remind_here_asks_for_the_pair_of_the_text_it_was_said_for() -> None:
    """Said in Figma, it stands; in the bank, Not here took it back; in the mail, the text
    changed after it, which withdraws it in the app, not from the text it was said for."""
    figma, bank, mail = CONTEXTS
    evening = Revision(
        11,
        1,
        2,
        "quando apro Figma di sera",
        "esportare",
        "quando apro Figma di sera",
        created_at=T0 + 50_000,
    )
    ends = (Ends(Situation.CALL),)
    on_calls = Revision(20, 2, 1, "quando finisco la call", "scrivere", "", situations=ends)

    def said(reminder: int, context: Context, here: Here, seconds: int) -> ContextAnswer:
        return ContextAnswer(reminder, context, here, None, None, T0 + seconds * 1000)

    answers = (
        said(1, figma, Here.YES, 10),
        said(1, bank, Here.YES, 20),
        said(1, bank, Here.NO, 30),
        said(1, mail, Here.YES, 40),
        said(1, mail, Here.WITHDRAWN, 50),
        said(2, figma, Here.YES, 60),  # no remainder: no pair to label
    )
    day = Day(DAY, (), (), {10: ICONS, 11: evening, 20: on_calls}, answers=answers)
    assert labels.asked(day) == {
        key(figma, ICONS.remainder): True,
        key(mail, ICONS.remainder): True,
    }


def test_the_owners_share_starts_with_what_claude_is_unsure_of(tmp_path: Path) -> None:
    labelled = labels.prepare(PAIRS, labels.path_for(tmp_path, DAY), DAY)
    labelled.uncertain = [MAIL]
    share = labels.owner_share(labelled, 2)
    assert share[0] == MAIL and len(share) == 2
    assert labels.owner_share(labelled, 2) == share  # the same draw every time
    assert sorted(labels.owner_share(labelled, 10)) == sorted(PAIRS)


def test_an_answer_must_be_about_a_pair_and_be_true_or_false(tmp_path: Path) -> None:
    labelled = labels.prepare(PAIRS, labels.path_for(tmp_path, DAY), DAY)
    with pytest.raises(ValueError, match="unknown pair"):
        labelled.answer("0123456789abcdef", True)
    with pytest.raises(TypeError, match="true or false"):
        labelled.answer(FIGMA, "yes")
    labelled.answer(FIGMA, False)
    assert labels.load(labelled.path).owner == {FIGMA: False}


def test_labels_in_the_wrong_shape_are_refused(tmp_path: Path) -> None:
    path = labels.prepare(PAIRS, labels.path_for(tmp_path, DAY), DAY).path
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(record | {"claude": {FIGMA: "sì"}}), encoding="utf-8")
    with pytest.raises(HarnessError, match='under "claude" must be true or false'):
        labels.load(path)
    path.write_text(json.dumps(record | {"format": 1}), encoding="utf-8")  # it named conditions
    with pytest.raises(HarnessError, match="format 1, not 2: move it away"):
        labels.load(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(HarnessError, match="not valid JSON"):
        labels.load(path)
    with pytest.raises(HarnessError, match="run label"):
        labels.load(tmp_path / "missing.json")
