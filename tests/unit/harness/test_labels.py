import json
from datetime import date
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.records import Revision
from jiffin.harness import labels
from jiffin.harness.day import Pair
from jiffin.harness.errors import HarnessError

DAY = date(2026, 10, 5)
ICONS = Revision(10, 1, 1, "quando apro Figma", "esportare le icone", "quando apro Figma")
PAIRS = {
    pair.key: pair
    for pair in (
        Pair(Context("figma.exe", "Icone - Figma", None), ICONS),
        Pair(Context("vivaldi.exe", "Banca Rossi", "bancarossi.it"), ICONS),
        Pair(Context("outlook.exe", "Posta in arrivo", None), ICONS),
    )
}
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
        "condition": "quando apro Figma",
        "action": "esportare le icone",
    }
    assert (record["claude"], record["uncertain"], record["owner"]) == ({}, [], {})
    assert "Quando" in record["instructions"]


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
    path.write_text(json.dumps(record | {"format": 2}), encoding="utf-8")
    with pytest.raises(HarnessError, match="format 2"):
        labels.load(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(HarnessError, match="not valid JSON"):
        labels.load(path)
    with pytest.raises(HarnessError, match="run label"):
        labels.load(tmp_path / "missing.json")
