import pytest

from jiffin.core.context import Context, normalize


@pytest.mark.parametrize(
    ("raw", "app"),
    [
        ("Code.exe", "code.exe"),
        ("vivaldi.exe", "vivaldi.exe"),
        ("WINWORD.EXE", "winword.exe"),
        ("olk", "olk"),
    ],
)
def test_app_is_the_lowercase_executable_name_with_its_extension(raw: str, app: str) -> None:
    assert normalize(raw, "", None).app == app


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        ("Progetto Rossi – changelog - Vivaldi", "Progetto Rossi – changelog"),
        ("Posta in arrivo - Google Chrome", "Posta in arrivo"),
        ("Banca Rossi - Brave", "Banca Rossi"),
        ("(3) WhatsApp", "WhatsApp"),
        ("(99+) Posta in arrivo - Vivaldi", "Posta in arrivo"),
        (
            "● changelog.md - jiffin - Visual Studio Code",
            "changelog.md - jiffin - Visual Studio Code",
        ),
        ("*Senza titolo - Blocco note", "Senza titolo - Blocco note"),
        ("appunti.txt *", "appunti.txt"),
        ("appunti.txt ●", "appunti.txt"),
        ("Relazione (3) finale.docx - Word", "Relazione (3) finale.docx - Word"),
        ("Vivaldi", "Vivaldi"),
        ("", ""),
    ],
)
def test_title_normalization(raw: str, title: str) -> None:
    assert normalize("app", raw, None).title == title


@pytest.mark.parametrize(
    ("raw", "address"),
    [
        ("https://www.github.com/rossi/app/?tab=readme#top", "github.com/rossi/app"),
        ("http://localhost:8080/", "localhost:8080"),
        ("github.com/rossi/app", "github.com/rossi/app"),
        ("https://mail.google.com/mail/u/0/#inbox", "mail.google.com/mail/u/0"),
        ("vivaldi://settings/", "settings"),
        ("about:blank", "about:blank"),
        ("https://", None),
        ("", None),
        (None, None),
    ],
)
def test_address_normalization(raw: str | None, address: str | None) -> None:
    assert normalize("vivaldi.exe", "", raw).address == address


def test_chrome_shortened_address_and_vivaldi_full_address_give_the_same_key() -> None:
    chrome = normalize("chrome.exe", "Progetto Rossi", "github.com/rossi/app")
    vivaldi = normalize("vivaldi.exe", "Progetto Rossi", "https://www.github.com/rossi/app/")
    assert chrome.address == vivaldi.address == "github.com/rossi/app"


def test_contexts_that_normalize_alike_are_one_key() -> None:
    first = normalize("Code.exe", "● changelog.md - jiffin", None)
    second = normalize("code.exe", "changelog.md - jiffin", None)
    assert first == second
    assert {first: "cached"}[second] == "cached"


def test_without_an_address_the_context_is_app_and_title() -> None:
    unreadable = normalize("chrome.exe", "Progetto Rossi - Google Chrome", None)
    assert unreadable == Context("chrome.exe", "Progetto Rossi", None)
    assert unreadable != normalize("chrome.exe", "Progetto Rossi", "github.com/rossi")
