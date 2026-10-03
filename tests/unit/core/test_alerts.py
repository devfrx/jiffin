from dataclasses import replace

from jiffin.core.alerts import MAX_VISIBLE, Alerts
from jiffin.core.context import Context
from jiffin.core.records import Alert, Revision

NOW = 1_790_000_000_000
REVISION = Revision(
    1, 1, 1, "quando apro Figma", "esportare le icone", "quando apro Figma", "The user opens Figma."
)


def alert(alert_id: int, reminder_id: int | None = None) -> Alert:
    context = Context("figma.exe", "Icone", None)
    reminder_id = alert_id if reminder_id is None else reminder_id
    return Alert(alert_id, reminder_id, REVISION, 1, context, 2.0, NOW, NOW)


def test_an_alert_is_shown_at_once_when_there_is_room() -> None:
    alerts = Alerts()
    assert alerts.add(alert(1), NOW).shown_at == NOW
    assert alerts.view().visible == (replace(alert(1), shown_at=NOW),)


def test_at_most_three_alerts_are_visible_and_the_others_wait() -> None:
    alerts = Alerts()
    placed = [alerts.add(alert(i), NOW) for i in range(1, 6)]
    assert [a.shown_at for a in placed] == [NOW, NOW, NOW, None, None]
    view = alerts.view()
    assert len(view.visible) == MAX_VISIBLE
    assert view.waiting == 2
    assert view.dot


def test_a_free_place_goes_to_the_first_waiting_alert() -> None:
    alerts = Alerts()
    for i in range(1, 5):
        alerts.add(alert(i), NOW)
    shown = alerts.close(2, NOW + 500)
    assert [(a.id, a.shown_at) for a in shown] == [(4, NOW + 500)]
    assert [a.id for a in alerts.view().visible] == [1, 3, 4]


def test_a_vanished_alert_goes_on_top_of_the_tray_list_until_seen() -> None:
    alerts = Alerts()
    alerts.add(alert(1), NOW)
    alerts.add(alert(2), NOW)
    [vanished] = alerts.vanish(1, NOW + 10_000)
    assert (vanished.id, vanished.vanished_at) == (1, NOW + 10_000)
    alerts.vanish(2, NOW + 10_000)
    view = alerts.view()
    assert view.visible == ()
    assert [a.id for a in view.unseen] == [2, 1]
    assert view.dot
    seen = alerts.see(NOW + 60_000)
    assert [(a.id, a.seen_at) for a in seen] == [(2, NOW + 60_000), (1, NOW + 60_000)]
    assert not alerts.view().dot
    assert alerts.see(NOW + 90_000) == []


def test_only_a_visible_alert_can_vanish() -> None:
    alerts = Alerts()
    for i in range(1, 5):
        alerts.add(alert(i), NOW)
    assert alerts.vanish(4, NOW) == []
    assert alerts.view().waiting == 1


def test_open_alerts_are_found_wherever_they_are() -> None:
    alerts = Alerts()
    for i in range(1, 5):
        alerts.add(alert(i), NOW)
    alerts.vanish(1, NOW)
    assert [alerts.find(i) is not None for i in range(1, 6)] == [True, True, True, True, False]
    assert [a.id for a in alerts.of(4)] == [4]


def test_the_tray_list_keeps_the_newest_unseen_alert_of_each_reminder() -> None:
    alerts = Alerts()
    alerts.add(alert(1, reminder_id=7), NOW)
    alerts.vanish(1, NOW + 10_000)
    alerts.add(alert(2, reminder_id=8), NOW + 20_000)
    alerts.vanish(2, NOW + 30_000)
    alerts.add(alert(3, reminder_id=7), NOW + 200_000)
    assert [a.id for a in alerts.view().unseen] == [2]
    alerts.vanish(3, NOW + 210_000)
    assert [a.id for a in alerts.view().unseen] == [3, 2]


def test_an_older_alert_that_vanishes_late_leaves_the_newer_one_in_the_tray_list() -> None:
    alerts = Alerts()
    alerts.add(alert(1, reminder_id=7), NOW)
    alerts.add(alert(2, reminder_id=7), NOW + 200_000)
    alerts.vanish(2, NOW + 210_000)
    [vanished] = alerts.vanish(1, NOW + 220_000)
    assert vanished.vanished_at == NOW + 220_000
    assert [a.id for a in alerts.view().unseen] == [2]
