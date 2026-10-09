"""What Texts.qml asks the Catalog for (ADR-0026): a text by its key, and each sentence with a
number, a size or a list in it. The windows' tests see them in their places."""

import pytest

from jiffin.lang.texts import GIB
from jiffin.ui.catalog import Catalog

ARRIVED, MODEL = 0.8 * GIB, 2600224416
"""What a download has, of the model's bytes."""


@pytest.fixture
def catalog() -> Catalog:
    return Catalog()


def test_a_text_is_found_by_its_key(catalog: Catalog) -> None:
    assert catalog.text("alert.done") == "Fatto"
    assert catalog.text("material.mica_alt.name") == "Mica Alt"


@pytest.mark.parametrize(
    "key",
    ["alert.undone", "alert", "alert.done.x", "alert.__doc__", "tray_list.silenced", "browser.x"],
)
def test_a_key_that_is_not_a_text_raises(catalog: Catalog, key: str) -> None:
    with pytest.raises(KeyError):
        catalog.text(key)


def test_a_download_says_what_arrived_and_the_minutes_left(catalog: Catalog) -> None:
    assert catalog.downloaded(ARRIVED, MODEL, 4) == "0,8 GB di 2,4 GB · circa 4 min"
    assert catalog.downloaded(ARRIVED, MODEL, 0) == "0,8 GB di 2,4 GB · meno di un minuto"
    assert catalog.downloaded(ARRIVED, MODEL, -1) == "0,8 GB di 2,4 GB"
    assert catalog.stopped(ARRIVED, MODEL) == "0,8 GB di 2,4 GB · fermo"
    assert catalog.downloading(ARRIVED, MODEL, 4) == (
        "Scarico il modello: 0,8 GB di 2,4 GB · circa 4 min. Finché non è pronto, i promemoria "
        "non avvisano."
    )


@pytest.mark.parametrize(
    ("missing", "size"), [(1, "0,1 GB"), (GIB, "1,0 GB"), (GIB + 1, "1,1 GB"), (MODEL, "2,5 GB")]
)
def test_a_full_disk_asks_for_the_tenths_of_a_gigabyte_missing_rounded_up(
    catalog: Catalog, missing: float, size: str
) -> None:
    assert catalog.space(missing) == f"Il disco è pieno: libera altri {size}, poi riprova."


def test_the_model_put_by_hand_has_its_name_and_its_bytes_with_their_thousands(
    catalog: Catalog,
) -> None:
    assert catalog.byHandPlace("model.gguf") == (
        "2. Mettilo nella cartella dei modelli, con il nome model.gguf:"
    )
    assert catalog.byHandCheck(MODEL, "79de5cb8") == (
        "3. Premi Riprova: lo controllo. Deve pesare 2.600.224.416 byte, con sha256 79de5cb8."
    )


@pytest.mark.parametrize(
    ("condition", "action", "perennial", "sentence"),
    [
        ("Quando apro Teams", "bere", False, "Quando apro Teams, ti ricordo di bere."),
        ("Quando apro Teams", "bere", True, "Quando apro Teams, ti ricordo ogni volta di bere."),
        ("Quando apro Teams", "", False, "Quando apro Teams, ti ricordo di …"),
        ("", "bere", True, "Quando …, ti ricordo ogni volta di bere."),
        ("", "", False, "Quando …, ti ricordo di …"),
    ],
)
def test_the_two_boxes_make_one_sentence(
    catalog: Catalog, condition: str, action: str, perennial: bool, sentence: str
) -> None:
    assert catalog.preview(condition, action, perennial) == sentence


def test_the_words_not_understood_are_each_quoted(catalog: Catalog) -> None:
    assert catalog.notUnderstood(["verso sera"]) == (
        "Non capisco «verso sera»: suona a qualsiasi ora."
    )
    assert catalog.notUnderstood(["verso sera", "a dicembre", "più tardi"]) == (
        "Non capisco «verso sera», «a dicembre» e «più tardi»: suona a qualsiasi ora."
    )


def test_a_time_already_over_is_named(catalog: Catalog) -> None:
    assert catalog.past("Oggi alle 09:00") == (
        "Oggi alle 09:00 è già passato. Per salvare, scrivi un giorno o un'ora che deve ancora "
        "venire."
    )


@pytest.mark.parametrize(
    ("ended_on", "returns_in", "returns_at", "tomorrow", "status"),
    [
        ("", 0, "", False, ""),
        ("il 20 ottobre", 0, "", False, "Periodo finito il 20 ottobre"),
        ("", 5, "15:30", True, "Rimandato: torna tra 5 min"),
        ("", 0, "15:30", False, "Rimandato: torna alle 15:30"),
        ("il 20 ottobre", 0, "08:00", True,
         "Periodo finito il 20 ottobre · Rimandato: torna domani alle 08:00"),
    ],
)  # fmt: skip
def test_an_active_reminder_says_what_is_useful_on_one_line(
    catalog: Catalog,
    ended_on: str,
    returns_in: int,
    returns_at: str,
    tomorrow: bool,
    status: str,
) -> None:
    assert catalog.status(ended_on, returns_in, returns_at, tomorrow) == status


@pytest.mark.parametrize(
    ("silences", "requests", "attentive", "learned"),
    [
        (0, 0, False, ""),
        (1, 0, False, "Taciuto in 1 posto"),
        (0, 1, False, "Chiesto in 1 posto"),
        (2, 3, False, "Taciuto in 2 posti · Chiesto in 3 posti"),
        (0, 2, True, "Chiesto in 2 posti · Più attento"),
        (1, 2, True, "Taciuto in 1 posto · Chiesto in 2 posti · Più attento"),
    ],
)
def test_what_a_reminder_learned_is_one_line_of_counts_and_never_a_number_of_its_threshold(
    catalog: Catalog, silences: int, requests: int, attentive: bool, learned: str
) -> None:
    assert catalog.learned(silences, requests, attentive) == learned


def test_the_completed_reminders_row_says_how_many(catalog: Catalog) -> None:
    assert catalog.completed(3) == "Completati · 3"


def test_a_pause_says_until_when(catalog: Catalog) -> None:
    assert catalog.pausedUntil("15:30", False) == "In pausa fino alle 15:30."
    assert catalog.pausedUntil("08:00", True) == "In pausa fino a domani alle 08:00."


@pytest.mark.parametrize(
    ("seconds", "pause"), [(120, "2 min"), (60, "1 min"), (90, "90 s"), (10, "10 s")]
)
def test_the_return_pause_is_in_minutes_when_it_is_whole_minutes(
    catalog: Catalog, seconds: int, pause: str
) -> None:
    assert catalog.returnsAfter(seconds) == (
        f"Gli avvisi tornano se riprendi una cosa dopo almeno {pause}."
    )


def test_the_browsers_whose_address_cannot_be_read_go_by_their_names(catalog: Catalog) -> None:
    assert catalog.unreadable(["chrome.exe", "brave.exe"]) == (
        "Chrome e Brave: non riesco a leggere l'indirizzo. Uso solo app e titolo."
    )
    assert catalog.unreadable(["vivaldi.exe", "arc.exe"]).startswith("Vivaldi e arc.exe: ")
