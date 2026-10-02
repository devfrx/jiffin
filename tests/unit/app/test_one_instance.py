import uuid

from jiffin.app import win32


def test_only_the_first_to_ask_holds_the_mutex() -> None:
    name = f"Local\\jiffin-test-{uuid.uuid4()}"
    assert win32.first_instance(name)
    assert not win32.first_instance(name)
