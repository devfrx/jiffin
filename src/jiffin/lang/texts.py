"""The texts of the interface (ADR-0026), from `it/texts.toml`: `TEXTS`, by the file's keys, and
the numbers, sizes and lists written as the language writes them."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from jiffin.lang import Plural, read

GIB = 1 << 30
"""A gigabyte as Windows' Explorer counts it: 1,024³ bytes."""


@dataclass(frozen=True, slots=True)
class Format:
    thousands: str
    decimal: str
    gigabytes: str
    comma: str
    conjunction: str
    quoted: str
    parts: str


@dataclass(frozen=True, slots=True)
class App:
    name: str
    cannot_start: str


@dataclass(frozen=True, slots=True)
class Command:
    close: str
    cancel: str
    retry: str
    retrying: str


@dataclass(frozen=True, slots=True)
class Alert:
    title: str
    done: str
    snooze: str
    not_here: str


@dataclass(frozen=True, slots=True)
class Snooze:
    next_time: str
    quarter_hour: str
    hour: str
    tomorrow: str


@dataclass(frozen=True, slots=True)
class Creation:
    new: str
    edit: str
    condition: str
    condition_hint: str
    condition_example: str
    action: str
    action_example: str
    perennial: str
    perennial_hint: str
    save: str
    no_condition: str
    preview: str
    preview_no_action: str
    preview_perennial: str
    preview_perennial_no_action: str
    not_understood: str
    situations_not_understood: str
    meant: str
    meant_action: str
    judged: str
    past: str


@dataclass(frozen=True, slots=True)
class Settings:
    title: str
    return_pause: str
    return_pause_hint: str
    unit: str
    seconds: str
    minutes: str
    material: str
    material_hint: str
    solid: str


@dataclass(frozen=True, slots=True)
class Networks:
    title: str
    hint: str
    home: str
    office: str
    neither: str
    offline: str
    unknown_home: str
    unknown_office: str
    waiting_home: str
    waiting_office: str
    at_home: str
    at_office: str


@dataclass(frozen=True, slots=True)
class Material:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class Materials:
    """By `ui.look.Material`."""

    acrylic: Material
    menu_acrylic: Material
    mica: Material
    mica_alt: Material


@dataclass(frozen=True, slots=True)
class NumberBox:
    increase: str
    decrease: str


@dataclass(frozen=True, slots=True)
class FirstRun:
    welcome: str
    is_ready: str
    only_here: str
    step_download: str
    step_check: str
    step_ready: str
    progress: str
    progress_minutes: str
    progress_under_minute: str
    progress_stopped: str
    meanwhile: str
    meanwhile_tray: str
    ready_shortcut: str
    shortcut_taken: str
    ready_tray: str
    start: str
    details: str
    by_hand: str
    by_hand_offline: str
    by_hand_fetch: str
    by_hand_place: str
    by_hand_check: str
    copy_address: str
    open_folder: str


@dataclass(frozen=True, slots=True)
class ModelFile:
    """By `ui.first_run.FirstRun.Stage`, its problems only."""

    network: str
    space: str
    disk: str
    mismatch: str


@dataclass(frozen=True, slots=True)
class Tray:
    quit: str
    pause_hour: str
    pause_tomorrow: str
    resume: str
    paused: str


@dataclass(frozen=True, slots=True)
class TrayList:
    title: str
    new: str
    unseen: str
    active: str
    no_reminders: str
    edit: str
    complete: str
    completed: str
    completed_when: str
    reopen: str
    delete: str
    delete_question: str
    change: str
    downloading: str
    paused_until: str
    paused_until_tomorrow: str
    unreadable: str
    period_over: str
    returns_in: str
    returns_at: str
    returns_tomorrow_at: str
    silenced: Plural
    requested: Plural
    attentive: str
    forget: str
    forget_all: str
    returns_after_minutes: str
    returns_after_seconds: str


@dataclass(frozen=True, slots=True)
class RemindHere:
    title: str
    question: str
    no_place: str
    outside_time: str
    period_over: str
    outside_situation: str
    silenced: str
    snoozed: str
    same_occasion: str


@dataclass(frozen=True, slots=True)
class Engine:
    """By `ui.tray_list.TrayList.Engine`, all but WORKING."""

    restarting: str
    failures: str
    model: str
    gpu_memory: str
    mismatch: str


@dataclass(frozen=True, slots=True)
class Texts:
    format: Format
    app: App
    command: Command
    alert: Alert
    snooze: Snooze
    creation: Creation
    settings: Settings
    networks: Networks
    material: Materials
    number_box: NumberBox
    first_run: FirstRun
    model_file: ModelFile
    tray: Tray
    tray_list: TrayList
    remind_here: RemindHere
    engine: Engine
    browser: Mapping[str, str]
    """By the browser's app, "chrome.exe"."""


TEXTS = read(Texts, "texts.toml")


def number(value: float, decimals: int = 0) -> str:
    """ "2.600.224.416", "2,4": rounded half up from the exact value, so 0.25 is "0,3"."""
    rounded = Decimal(value).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    marks = {ord(","): TEXTS.format.thousands, ord("."): TEXTS.format.decimal}
    return f"{rounded:,f}".translate(marks)


def gigabytes(size: float) -> str:
    """A size in bytes as Windows' Explorer shows it, in gigabytes with one decimal: "2,4 GB"."""
    return TEXTS.format.gigabytes.format(size=number(size / GIB, 1))


def listed(items: Sequence[str]) -> str:
    """ "Chrome e Brave", "Vivaldi, Chrome e Brave"; one item alone, and nothing for none."""
    if len(items) < 2:
        return "".join(items)
    return TEXTS.format.comma.join(items[:-1]) + TEXTS.format.conjunction + items[-1]
