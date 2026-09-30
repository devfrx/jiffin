from jiffin.platform import win32


def test_a_title_cut_inside_an_emoji_can_still_reach_the_engine() -> None:
    cut = "Piano \U0001f5d3"[:-1] + "\ud83d"  # the first half of a surrogate pair
    assert win32.clean(cut) == "Piano �"
    assert win32.clean(cut).encode()
    assert win32.clean("Piano \U0001f5d3 fatto") == "Piano \U0001f5d3 fatto"
