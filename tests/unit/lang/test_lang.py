"""The language files (ADR-0026): each read once into frozen dataclasses, which a key missing,
one too many or of the wrong kind stops; and the rules that write counts, numbers, sizes and
lists in Italian."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

import jiffin.lang
from jiffin.lang import CatalogError, Plural, read
from jiffin.lang.texts import GIB, gigabytes, listed, number


@dataclass(frozen=True, slots=True)
class Door:
    open: str
    count: Plural


@dataclass(frozen=True, slots=True)
class House:
    name: str
    door: Door
    rooms: Mapping[str, str]


HOUSE = """
name = "Casa"
rooms = { "a.exe" = "Cucina" }

[door]
open = "Apri {what}"
count = { one = "{count} porta", other = "{count} porte" }
"""


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The language's folder, empty until a test writes its file."""
    monkeypatch.setattr(jiffin.lang, "FOLDER", tmp_path)
    return tmp_path


def house(folder: Path, text: str = HOUSE) -> House:
    (folder / "house.toml").write_bytes(text.encode("utf-8"))
    return read(House, "house.toml")


def test_a_file_is_read_into_its_dataclasses(folder: Path) -> None:
    read_house = house(folder)
    assert read_house.name == "Casa"
    assert read_house.door.open.format(what="tutto") == "Apri tutto"
    assert read_house.door.count.format(3) == "3 porte"
    assert read_house.rooms["a.exe"] == "Cucina"
    with pytest.raises(TypeError):
        read_house.rooms["b.exe"] = "Bagno"  # type: ignore[index]


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        ('open = "Apri {what}"', 'shut = "Chiudi"', "door.open is missing, door.shut is not read"),
        ('name = "Casa"', 'name = "Casa"\nroof = "Tetto"', "roof is not read"),
        ('name = "Casa"', "name = 1", "name is not a text"),
        ('rooms = { "a.exe" = "Cucina" }', 'rooms = "Cucina"', "rooms is not a table of texts"),
        ('"a.exe" = "Cucina"', '"a.exe" = 1', "rooms is not a table of texts"),
        ('count = { one = "{count} porta", other = "{count} porte" }', 'count = "porte"',
         "door.count is not a table"),
        ('count = { one = "{count} porta", other = "{count} porte" }', 'count = { one = "porta" }',
         "door.count.other is missing"),
    ],
)  # fmt: skip
def test_a_key_missing_one_too_many_or_of_the_wrong_kind_stops_the_read(
    folder: Path, old: str, new: str, problem: str
) -> None:
    assert old in HOUSE
    with pytest.raises(CatalogError) as raised:
        house(folder, HOUSE.replace(old, new))
    assert str(raised.value) == f"house.toml: {problem}"


def test_a_file_missing_or_not_toml_stops_the_read(folder: Path) -> None:
    with pytest.raises(CatalogError, match=r"^house\.toml: "):
        read(House, "house.toml")
    with pytest.raises(CatalogError, match=r"^house\.toml: "):
        house(folder, 'name = "Casa')


def test_the_singular_is_for_one_alone() -> None:
    places = Plural(one="Taciuto in {count} posto", other="Taciuto in {count} posti")
    assert [places.format(count) for count in (0, 1, 2, 21)] == [
        "Taciuto in 0 posti",
        "Taciuto in 1 posto",
        "Taciuto in 2 posti",
        "Taciuto in 21 posti",
    ]


@pytest.mark.parametrize(
    ("value", "decimals", "written"),
    [
        (2600224416, 0, "2.600.224.416"),
        (999, 0, "999"),
        (1234567.5, 0, "1.234.568"),
        (2.4, 1, "2,4"),
        (0, 1, "0,0"),
        (0.25, 1, "0,3"),  # a tie, exact in binary: up
        (2.675, 2, "2,67"),  # under 2.675 in binary: down
    ],
)
def test_a_number_has_its_thousands_and_its_decimal_comma_rounded_half_up(
    value: float, decimals: int, written: str
) -> None:
    assert number(value, decimals) == written


def test_a_size_is_in_gigabytes_of_1024_cubed_bytes_with_one_decimal() -> None:
    assert gigabytes(2600224416) == "2,4 GB"
    assert gigabytes(GIB / 4) == "0,3 GB"


def test_a_list_joins_its_last_two_with_e() -> None:
    lists = [[], ["Chrome"], ["Chrome", "Brave"], ["Vivaldi", "Chrome", "Brave"]]
    assert [listed(items) for items in lists] == [
        "",
        "Chrome",
        "Chrome e Brave",
        "Vivaldi, Chrome e Brave",
    ]
