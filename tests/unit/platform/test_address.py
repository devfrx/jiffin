import pytest

from jiffin.core.context import BROWSER_SUFFIXES
from jiffin.platform.address import BROWSERS, Outcome, Reading


def test_every_supported_browser_has_its_title_suffix() -> None:
    assert BROWSERS.keys() == BROWSER_SUFFIXES.keys()


@pytest.mark.parametrize(
    ("outcome", "contextual", "readable"),
    [
        (Outcome.ADDRESS, True, True),
        (Outcome.TYPING, True, True),
        (Outcome.PRIVATE, False, True),
        (Outcome.FAILED, True, False),
        (Outcome.UNSURE, False, False),
    ],
)
def test_a_window_is_a_context_only_when_known_not_to_be_private(
    outcome: Outcome, contextual: bool, readable: bool
) -> None:
    assert (Reading(outcome).contextual, Reading(outcome).readable) == (contextual, readable)
