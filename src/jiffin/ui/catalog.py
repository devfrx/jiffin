"""The texts of the interface for QML (ADR-0026): Texts.qml reads every text through the `Catalog`
singleton, by its key in `jiffin.lang.texts`, and asks it for each sentence with a placeholder,
since QML writes no number, size or list of its own. Python reads `TEXTS` directly.

The windows' modules import this one before they load their QML, which registers `Catalog`.
"""

import math
from dataclasses import fields, is_dataclass

from PySide6.QtCore import QObject, Slot
from PySide6.QtQml import QmlElement, QmlSingleton

from jiffin.lang.texts import GIB, TEXTS, gigabytes, listed, number

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1


@QmlElement
@QmlSingleton
class Catalog(QObject):
    """Holds nothing: the texts are read once, at import, and never change."""

    @Slot(str, result=str)
    def text(self, key: str) -> str:
        """The text at a key of texts.toml, "alert.done"."""
        found: object = TEXTS
        for name in key.split("."):
            if not is_dataclass(found) or name not in {field.name for field in fields(found)}:
                raise KeyError(key)
            found = getattr(found, name)
        if not isinstance(found, str):
            raise KeyError(key)
        return found

    @Slot(float, float, int, result=str)
    def downloaded(self, done: float, total: float, minutes: int) -> str:
        """Under the download's bar, "0,8 GB di 2,4 GB · circa 4 min": `minutes` left, 0 under a
        minute, negative while unknown."""
        sizes = {"done": gigabytes(done), "total": gigabytes(total)}
        if minutes > 0:
            return TEXTS.first_run.progress_minutes.format(minutes=minutes, **sizes)
        if minutes == 0:
            return TEXTS.first_run.progress_under_minute.format(**sizes)
        return TEXTS.first_run.progress.format(**sizes)

    @Slot(float, float, result=str)
    def stopped(self, done: float, total: float) -> str:
        return TEXTS.first_run.progress_stopped.format(done=gigabytes(done), total=gigabytes(total))

    @Slot(float, float, int, result=str)
    def downloading(self, done: float, total: float, minutes: int) -> str:
        """The tray list's line while the model downloads."""
        return TEXTS.tray_list.downloading.format(progress=self.downloaded(done, total, minutes))

    @Slot(float, result=str)
    def space(self, missing: float) -> str:
        """A disk too full for the model, `missing` bytes short: in tenths of a gigabyte rounded
        up, so that freeing what it says is enough."""
        tenths = math.ceil(missing * 10 / GIB)
        return TEXTS.model_file.space.format(size=gigabytes(tenths * GIB / 10))

    @Slot(str, result=str)
    def byHandPlace(self, name: str) -> str:
        return TEXTS.first_run.by_hand_place.format(name=name)

    @Slot(float, str, result=str)
    def byHandCheck(self, size: float, sha256: str) -> str:
        return TEXTS.first_run.by_hand_check.format(size=number(size), sha256=sha256)

    @Slot(str, str, bool, result=str)
    def preview(self, condition: str, action: str, perennial: bool) -> str:
        """The sentence the creation window's two boxes make: "Quando apro Teams, ti ricordo di
        bere un bicchiere d'acqua."."""
        texts = TEXTS.creation
        if perennial:
            sentence = texts.preview_perennial if action else texts.preview_perennial_no_action
        else:
            sentence = texts.preview if action else texts.preview_no_action
        return sentence.format(condition=condition or texts.no_condition, action=action)

    @Slot("QStringList", result=str)
    def notUnderstood(self, words: list[str]) -> str:
        return TEXTS.creation.not_understood.format(words=_quoted(words))

    @Slot("QStringList", result=str)
    def situationsNotUnderstood(self, words: list[str]) -> str:
        return TEXTS.creation.situations_not_understood.format(words=_quoted(words))

    @Slot("QStringList", result=str)
    def meant(self, words: list[str]) -> str:
        return TEXTS.creation.meant.format(words=_quoted(words))

    @Slot(str, result=str)
    def judged(self, what: str) -> str:
        return TEXTS.creation.judged.format(what=TEXTS.format.quoted.format(text=what))

    @Slot(str, result=str)
    def past(self, when: str) -> str:
        return TEXTS.creation.past.format(when=when)

    @Slot(str, int, str, bool, result=str)
    def status(self, ended_on: str, returns_in: int, returns_at: str, tomorrow: bool) -> str:
        """Under an active reminder, what is useful to know: its period over, "il 20 ottobre", and
        the minutes or the time its snooze ends."""
        texts = TEXTS.tray_list
        parts = []
        if ended_on:
            parts.append(texts.period_over.format(on=ended_on))
        if returns_in > 0:
            parts.append(texts.returns_in.format(minutes=returns_in))
        elif returns_at:
            returns = texts.returns_tomorrow_at if tomorrow else texts.returns_at
            parts.append(returns.format(at=returns_at))
        return TEXTS.format.parts.join(parts)

    @Slot(int, int, bool, result=str)
    def learned(self, silences: int, requests: int, attentive: bool) -> str:
        """Under an active reminder, what it learned (ADR-0029): how many places Not here
        silenced it in and Remind here asked it in, and whether its threshold went down; empty
        when it learned nothing."""
        texts = TEXTS.tray_list
        parts = []
        if silences > 0:
            parts.append(texts.silenced.format(silences))
        if requests > 0:
            parts.append(texts.requested.format(requests))
        if attentive:
            parts.append(texts.attentive)
        return TEXTS.format.parts.join(parts)

    @Slot(int, result=str)
    def completed(self, count: int) -> str:
        """The row of the completed reminders in the tray list, "Completati · 3" (ADR-0030)."""
        return TEXTS.tray_list.completed.format(count=count)

    @Slot(str, bool, result=str)
    def pausedUntil(self, at: str, tomorrow: bool) -> str:
        texts = TEXTS.tray_list
        return (texts.paused_until_tomorrow if tomorrow else texts.paused_until).format(at=at)

    @Slot(int, result=str)
    def returnsAfter(self, seconds: int) -> str:
        """The return pause, in minutes when it is whole minutes, as the settings show it."""
        if seconds % 60 == 0:
            return TEXTS.tray_list.returns_after_minutes.format(minutes=seconds // 60)
        return TEXTS.tray_list.returns_after_seconds.format(seconds=seconds)

    @Slot("QStringList", result=str)
    def unreadable(self, apps: list[str]) -> str:
        """The browsers whose address cannot be read, by app: "chrome.exe" is "Chrome"."""
        names = [TEXTS.browser.get(app, app) for app in apps]
        return TEXTS.tray_list.unreadable.format(browsers=listed(names))


def _quoted(words: list[str]) -> str:
    """Words not understood, or meant, each quoted: "«verso sera» e «a dicembre»"."""
    return listed([TEXTS.format.quoted.format(text=word) for word in words])
