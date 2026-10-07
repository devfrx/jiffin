"""The check that keeps the Italian in the language files (ADR-0026): what it finds, where, and
what it lets through."""

import importlib.util
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_italian.py"
CORE = PurePosixPath("src/jiffin/core/clock.py")


@pytest.fixture(scope="module")
def check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_italian", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def found(check: ModuleType, path: str, text: str) -> list[tuple[int, str]]:
    words = check.vocabulary()
    return [(f.line, f.word) for f in check.findings(PurePosixPath(path), text, words)]


def test_the_words_are_those_of_the_language_files(check: ModuleType) -> None:
    words = check.vocabulary()
    # Texts, the lexicon's lists and its tables of words by number; the elision keeps its mark.
    assert {"rimanda", "lunedì", "ventitré", "all'", "ricordami"} <= words
    assert "done" not in words  # a key, not a text


def test_a_planted_italian_comment_fails(check: ModuleType) -> None:
    text = "NOW = 1\n# Il valore di adesso, da rivedere domani.\nLATER = 2  # poi Rimanda\n"
    assert found(check, str(CORE), text) == [
        (2, "Il"),
        (2, "di"),
        (2, "da"),
        (2, "domani"),
        (3, "poi"),
        (3, "Rimanda"),
    ]


def test_an_accented_word_is_italian_even_outside_the_language_files(check: ModuleType) -> None:
    assert found(check, str(CORE), "# così\n") == [(1, "così")]


def test_an_example_between_quotes_or_in_a_code_span_passes(check: ModuleType) -> None:
    text = (
        '"""Reads "quando apro Figma dopo\n'
        '    le 23", «alle 9» and `non_qui`."""\n'
        '# Over lines: "domani\n'
        '# alle 15".\n'
    )
    assert found(check, str(CORE), text) == []


def test_english_words_that_are_italian_too_pass(check: ModuleType) -> None:
    text = "# No file in the menu per app: Jiffin's log, in Chrome; the state, due now.\n"
    assert found(check, str(CORE), text) == []


def test_an_english_possessive_of_an_italian_word_is_italian(check: ModuleType) -> None:
    assert found(check, str(CORE), "# Rimanda's menu\n") == [(1, "Rimanda'")]


def test_literals_are_read_in_src_only(check: ModuleType) -> None:
    text = 'LABEL = "Rimanda"\n'
    assert found(check, str(CORE), text) == [(1, "Rimanda")]
    assert found(check, "tests/unit/core/test_clock.py", text) == []
    assert found(check, "scripts/package.py", text) == []


def test_the_examples_and_the_names_a_file_may_hold_pass(check: ModuleType) -> None:
    examples = 'SAMPLES = (("quando apro Teams", "bere"),)\n'
    assert found(check, "src/jiffin/ui/__main__.py", examples) == []
    assert found(check, "src/jiffin/engine/prompts.py", examples) == []
    records = 'DONE = "fatto"\nNOT_HERE = "non_qui"\nOTHER = "rimandato"\n'
    assert found(check, "src/jiffin/core/records.py", records) == [(3, "rimandato")]


def test_docs_are_read_outside_quotes_and_code_spans(check: ModuleType) -> None:
    text = (
        'Snooze, not Rimanda: "Tra 15 minuti" and `rimanda`.\n\n```mermaid\nA --> B : Esci\n```\n'
    )
    assert found(check, "docs/design/tray.md", text) == [(1, "Rimanda"), (4, "Esci")]
    assert found(check, "README.md", text) == [(1, "Rimanda"), (4, "Esci")]
    assert found(check, "docs/adr/0026-italian-in-language-files.md", text) == []
    assert found(check, "CHANGELOG.md", text) == []


def test_qml_comments_and_literals_are_read(check: ModuleType) -> None:
    text = '// Il pulsante\nText {\n    text: "Chiudi"\n    /* poi\n    Esci */\n}\n'
    assert found(check, "src/jiffin/ui/qml/AlertWindow.qml", text) == [
        (1, "Il"),
        (3, "Chiudi"),
        (4, "poi"),
        (5, "Esci"),
    ]


def test_a_page_of_src_holds_no_italian_even_between_quotes(check: ModuleType) -> None:
    text = '<p title="Chiudi">{{ t.label.title }}</p>\n'
    assert found(check, "src/jiffin/harness/pages/label.html", text) == [(1, "Chiudi")]


def test_a_migration_after_0002_may_name_the_old_answers_only(check: ModuleType) -> None:
    text = "-- Translate the answers.\nUPDATE alert SET answer = 'done' WHERE answer = 'fatto';\n"
    assert found(check, "src/jiffin/store/migrations/0003_english.sql", text) == []
    planted = text.replace("Translate", "Traduci le risposte, ")
    assert found(check, "src/jiffin/store/migrations/0003_english.sql", planted) == [(1, "le")]
    assert found(check, "src/jiffin/store/migrations/0002_one_alert_per_unit.sql", planted) == []


def test_configuration_files_are_read_in_their_comments(check: ModuleType) -> None:
    text = 'name = "Jiffin"  # il nome\nnote = "# not a comment"\n'
    assert found(check, "pyproject.toml", text) == [(1, "il"), (1, "nome")]


def test_the_language_files_are_not_read(check: ModuleType) -> None:
    assert found(check, "src/jiffin/lang/it/texts.toml", '# Il testo\ndone = "Fatto"\n') == []


def test_the_hook_names_each_word_and_fails(
    check: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(check, "REPO", tmp_path)
    planted = tmp_path / "src" / "jiffin" / "core" / "clock.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("# perché\n", encoding="utf-8")
    clean = tmp_path / "src" / "jiffin" / "core" / "units.py"
    clean.write_text("# Why\n", encoding="utf-8")
    assert check.main([str(clean)]) == 0
    assert check.main([str(planted), str(clean)]) == 1
    out = capsys.readouterr().out
    assert "src/jiffin/core/clock.py:1: perché" in out
    assert "1 Italian words outside the language files" in out
