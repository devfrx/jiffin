pragma Singleton

import QtQml
import Jiffin

// Every text of the interface, by its key in src/jiffin/lang/it/texts.toml (ADR-0026): a typed
// facade over the Catalog singleton, so that qmllint checks every use. It holds no text itself.
QtObject {
    // The alert, and Snooze's menu (#83)
    readonly property string reminder: Catalog.text("alert.title")
    readonly property string done: Catalog.text("alert.done")
    readonly property string snooze: Catalog.text("alert.snooze")
    readonly property string nextTime: Catalog.text("snooze.next_time")
    readonly property string inQuarterHour: Catalog.text("snooze.quarter_hour")
    readonly property string inHour: Catalog.text("snooze.hour")
    readonly property string tomorrow: Catalog.text("snooze.tomorrow")
    readonly property string notHere: Catalog.text("alert.not_here")

    // The creation window
    readonly property string newReminder: Catalog.text("creation.new")
    readonly property string editReminder: Catalog.text("creation.edit")
    readonly property string when: Catalog.text("creation.condition")
    readonly property string whenHint: Catalog.text("creation.condition_hint")
    readonly property string whenExample: Catalog.text("creation.condition_example")
    readonly property string remindMe: Catalog.text("creation.action")
    readonly property string remindMeExample: Catalog.text("creation.action_example")
    readonly property string everyTime: Catalog.text("creation.perennial")
    readonly property string everyTimeHint: Catalog.text("creation.perennial_hint")
    readonly property string save: Catalog.text("creation.save")
    readonly property string cancel: Catalog.text("command.cancel")

    // The settings window
    readonly property string settings: Catalog.text("settings.title")
    readonly property string returnPause: Catalog.text("settings.return_pause")
    readonly property string returnPauseHint: Catalog.text("settings.return_pause_hint")
    readonly property string unit: Catalog.text("settings.unit")
    // The return pause's units, by Preferences.minutes: false, then true.
    readonly property list<string> units: [Catalog.text("settings.seconds"), Catalog.text("settings.minutes")]
    readonly property string increase: Catalog.text("number_box.increase")
    readonly property string decrease: Catalog.text("number_box.decrease")
    readonly property string material: Catalog.text("settings.material")
    readonly property string materialHint: Catalog.text("settings.material_hint")
    // By the material's letter (ADR-0010): its name, and what it looks like.
    readonly property var materials: ({
            "a": [Catalog.text("material.acrylic.name"), Catalog.text("material.acrylic.description")],
            "b": [Catalog.text("material.menu_acrylic.name"), Catalog.text("material.menu_acrylic.description")],
            "c": [Catalog.text("material.mica.name"), Catalog.text("material.mica.description")],
            "d": [Catalog.text("material.mica_alt.name"), Catalog.text("material.mica_alt.description")]
        })
    readonly property string solidSurfaces: Catalog.text("settings.solid")
    readonly property string close: Catalog.text("command.close")

    // The first run (ADR-0015)
    readonly property string welcome: Catalog.text("first_run.welcome")
    readonly property string isReady: Catalog.text("first_run.is_ready")
    readonly property string onlyHere: Catalog.text("first_run.only_here")
    readonly property string stepDownload: Catalog.text("first_run.step_download")
    readonly property string stepCheck: Catalog.text("first_run.step_check")
    readonly property string stepReady: Catalog.text("first_run.step_ready")
    readonly property string meanwhile: Catalog.text("first_run.meanwhile")
    readonly property string meanwhileTray: Catalog.text("first_run.meanwhile_tray")
    readonly property string readyShortcut: Catalog.text("first_run.ready_shortcut")
    readonly property string shortcutTaken: Catalog.text("first_run.shortcut_taken")
    readonly property string readyTray: Catalog.text("first_run.ready_tray")
    readonly property string start: Catalog.text("first_run.start")
    readonly property string retrying: Catalog.text("command.retrying")
    readonly property string details: Catalog.text("first_run.details")
    readonly property string byHand: Catalog.text("first_run.by_hand")
    readonly property string byHandOffline: Catalog.text("first_run.by_hand_offline")
    readonly property string byHandFetch: Catalog.text("first_run.by_hand_fetch")
    readonly property string copyAddress: Catalog.text("first_run.copy_address")
    readonly property string openFolder: Catalog.text("first_run.open_folder")

    // Under the download's bar: "0,8 GB di 2,4 GB · circa 4 min".
    function downloaded(done: real, total: real, minutes: int): string {
        return Catalog.downloaded(done, total, minutes);
    }

    function stopped(done: real, total: real): string {
        return Catalog.stopped(done, total);
    }

    // The tray list's line while the model downloads.
    function downloading(done: real, total: real, minutes: int): string {
        return Catalog.downloading(done, total, minutes);
    }

    // What a problem with the model file means; `missing` in bytes, for SPACE.
    function modelTrouble(stage: int, missing: real): string {
        switch (stage) {
        case FirstRun.NETWORK:
            return Catalog.text("model_file.network");
        case FirstRun.SPACE:
            return Catalog.space(missing);
        case FirstRun.DISK:
            return Catalog.text("model_file.disk");
        case FirstRun.MISMATCH:
            return Catalog.text("model_file.mismatch");
        }
        return "";
    }

    function byHandPlace(name: string): string {
        return Catalog.byHandPlace(name);
    }

    // The size in bytes, with its thousands: "2.600.224.416".
    function byHandCheck(size: real, sha256: string): string {
        return Catalog.byHandCheck(size, sha256);
    }

    // The tray icon and its list
    readonly property string appName: Catalog.text("app.name")
    readonly property string quit: Catalog.text("tray.quit")
    readonly property string pauseHour: Catalog.text("tray.pause_hour")
    readonly property string pauseTomorrow: Catalog.text("tray.pause_tomorrow")
    readonly property string resume: Catalog.text("tray.resume")
    readonly property string paused: Catalog.text("tray.paused")
    readonly property string reminders: Catalog.text("tray_list.title")
    readonly property string newOne: Catalog.text("tray_list.new")
    readonly property string unseen: Catalog.text("tray_list.unseen")
    readonly property string active: Catalog.text("tray_list.active")
    readonly property string noReminders: Catalog.text("tray_list.no_reminders")
    readonly property string edit: Catalog.text("tray_list.edit")
    readonly property string complete: Catalog.text("tray_list.complete")
    readonly property string reopen: Catalog.text("tray_list.reopen")
    readonly property string remove: Catalog.text("tray_list.delete")
    readonly property string removeQuestion: Catalog.text("tray_list.delete_question")
    readonly property string retry: Catalog.text("command.retry")
    readonly property string change: Catalog.text("tray_list.change")
    readonly property string forget: Catalog.text("tray_list.forget")
    readonly property string forgetAll: Catalog.text("tray_list.forget_all")
    // Remind here (ADR-0029): the row at the top of the tray list, and the card it opens.
    readonly property string remindHere: Catalog.text("remind_here.title")
    readonly property string remindHereQuestion: Catalog.text("remind_here.question")
    readonly property string noPlace: Catalog.text("remind_here.no_place")
    // What the engine's trouble means, by TrayList.Engine; WORKING says nothing.
    readonly property var engineTrouble: ["", Catalog.text("engine.restarting"), Catalog.text("engine.failures"), Catalog.text("engine.model"), Catalog.text("engine.gpu_memory"), Catalog.text("engine.mismatch")]

    // The sentence the two boxes make (#12): "Quando …, ti ricordo di …", "ti ricordo ogni volta"
    // for a perennial reminder (#84).
    function preview(condition: string, action: string, perennial: bool): string {
        return Catalog.preview(condition, action, perennial);
    }

    // Under "Quando", for the words of a time not understood (#90): the reminder still saves,
    // without its time. "Non capisco «verso sera» e «a dicembre»: …".
    function notUnderstood(words: list<string>): string {
        return Catalog.notUnderstood(words);
    }

    // Under the sentence, while a time already over keeps Save off (#84): "Oggi alle 09:00 …".
    function past(when: string): string {
        return Catalog.past(when);
    }

    // Under an active reminder, when useful: its period over (#91), "il 20 ottobre", and its
    // snooze.
    function status(endedOn: string, returnsIn: int, returnsAt: string, tomorrow: bool): string {
        return Catalog.status(endedOn, returnsIn, returnsAt, tomorrow);
    }

    // Under an active reminder, what it learned (ADR-0029): "Taciuto in 2 posti · Chiesto in 1
    // posto · Più attento"; empty when nothing.
    function learned(silences: int, requests: int, attentive: bool): string {
        return Catalog.learned(silences, requests, attentive);
    }

    // The row of the completed reminders in the tray list (ADR-0030): "Completati · 3".
    function completed(count: int): string {
        return Catalog.completed(count);
    }

    // At the top of the tray list while Jiffin is paused (ADR-0024): "In pausa fino alle 15:30.",
    // "In pausa fino a domani alle 08:00.".
    function pausedUntil(at: string, tomorrow: bool): string {
        return Catalog.pausedUntil(at, tomorrow);
    }

    // At the bottom of the tray list (#84): the return pause, in minutes when it is whole
    // minutes, as the settings show it, else in seconds.
    function returnsAfter(seconds: int): string {
        return Catalog.returnsAfter(seconds);
    }

    // The browsers whose address cannot be read, by app: "Chrome e Brave: …".
    function unreadable(apps: list<string>): string {
        return Catalog.unreadable(apps);
    }
}
