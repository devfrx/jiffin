pragma Singleton

import QtQml
import Jiffin

// Every string of the interface, in Italian, in one place (#12).
QtObject {
    // The alert, and Rimanda's menu (#83)
    readonly property string reminder: "Promemoria"
    readonly property string done: "Fatto"
    readonly property string snooze: "Rimanda"
    readonly property string nextTime: "Alla prossima volta"
    readonly property string inQuarterHour: "Tra 15 minuti"
    readonly property string inHour: "Tra un'ora"
    readonly property string tomorrow: "Domani"
    readonly property string notHere: "Non qui"
    // Rimanda in the tray list's unseen cards, until it becomes the alert's menu (#84)
    readonly property string back: "Indietro"
    readonly property string quarterHour: "15 min"
    readonly property string hour: "1 ora"

    // The creation window
    readonly property string newReminder: "Nuovo promemoria"
    readonly property string editReminder: "Modifica promemoria"
    readonly property string when: "Quando"
    readonly property string whenHint: "Descrivi dove sei o quando: un'app, un sito, un orario."
    readonly property string whenExample: "quando lavoro al progetto Rossi"
    readonly property string remindMe: "Ricordami di"
    readonly property string remindMeExample: "aggiornare il changelog"
    readonly property string everyTime: "Ogni volta"
    readonly property string everyTimeHint: "Suona ogni volta che succede, e non si completa mai."
    readonly property string save: "Salva"
    readonly property string cancel: "Annulla"

    // The settings window
    readonly property string settings: "Impostazioni"
    readonly property string material: "Materiale"
    readonly property string materialHint: "Per gli avvisi, l'elenco e le altre finestre di Jiffin."
    // By the material's letter (ADR-0010): its name, and what it looks like.
    readonly property var materials: ({
            "a": ["Acrilico", "Vetro chiaro: dietro si vede sfocato."],
            "b": ["Acrilico dei menu", "Quasi pieno, come i menu di Windows. Predefinito."],
            "c": ["Mica", "Come le Impostazioni di Windows: prende il colore dello sfondo."],
            "d": ["Mica Alt", "Più scuro, con più colore dello sfondo."]
        })
    readonly property string solidSurfaces: "Gli effetti di trasparenza di Windows sono spenti: le finestre sono piene."
    readonly property string close: "Chiudi"

    // The first run (ADR-0015)
    readonly property string welcome: "Benvenuto in Jiffin"
    readonly property string isReady: "Jiffin è pronto"
    readonly property string onlyHere: "Jiffin lavora solo su questo PC: niente esce da qui."
    readonly property string stepDownload: "Scarico il modello"
    readonly property string stepCheck: "Controllo il file"
    readonly property string stepReady: "Pronto"
    readonly property string meanwhile: "Intanto puoi già scrivere i promemoria: premi Win+Maiusc+N."
    readonly property string meanwhileTray: "Intanto puoi già scrivere i promemoria: Nuovo, nell'elenco dell'icona di Jiffin."
    readonly property string readyShortcut: "Premi Win+Maiusc+N, da qualsiasi app, per un nuovo promemoria."
    readonly property string shortcutTaken: "Win+Maiusc+N è già di un'altra app: un nuovo promemoria si scrive da Nuovo, nell'elenco."
    readonly property string readyTray: "L'icona di Jiffin nella barra apre l'elenco. Windows la mette sotto ^: trascinala sulla barra per vederla sempre."
    readonly property string start: "Inizia"
    readonly property string retrying: "Riprovo…"
    readonly property string details: "Dettagli"
    readonly property string byHand: "Mettilo a mano"
    readonly property string byHandOffline: "Senza rete? Mettilo a mano"
    readonly property string byHandFetch: "1. Scarica il file da questo indirizzo, anche da un altro PC:"
    readonly property string copyAddress: "Copia l'indirizzo"
    readonly property string openFolder: "Apri la cartella"

    // The model's size, as Windows' Explorer shows it: gigabytes of 1,024³ bytes, one decimal.
    function gigabytes(bytes: real): string {
        return (bytes / 1073741824).toFixed(1).replace(".", ",") + " GB";
    }

    // Under the download's bar: "0,8 GB di 2,4 GB · circa 4 min".
    function downloaded(done: real, total: real, minutes: int): string {
        const left = minutes > 0 ? " · circa " + minutes + " min" : minutes === 0 ? " · meno di un minuto" : "";
        return gigabytes(done) + " di " + gigabytes(total) + left;
    }

    function stopped(done: real, total: real): string {
        return gigabytes(done) + " di " + gigabytes(total) + " · fermo";
    }

    // The tray list's line while the model downloads.
    function downloading(done: real, total: real, minutes: int): string {
        return "Scarico il modello: " + downloaded(done, total, minutes) + ". Finché non è pronto, i promemoria non avvisano.";
    }

    // What a problem with the model file means; `missing` in bytes, for SPACE.
    function modelTrouble(stage: int, missing: real): string {
        switch (stage) {
        case FirstRun.NETWORK:
            return "Il download si è fermato: controlla la connessione. Riprova riprende da dove era rimasto.";
        case FirstRun.SPACE:
            // In tenths, rounded up, so that freeing what it says is enough; the division by a
            // power of two is exact.
            return "Il disco è pieno: libera altri " + gigabytes(Math.ceil(missing * 10 / 1073741824) * 107374182.4) + ", poi riprova.";
        case FirstRun.DISK:
            return "Non riesco a scrivere nella cartella dei modelli, o a leggerla. Controlla il disco, poi riprova.";
        case FirstRun.MISMATCH:
            return "Il file del modello non è quello giusto. Se l'hai messo tu, sostituiscilo o eliminalo; poi premi Riprova.";
        }
        return "";
    }

    function byHandPlace(name: string): string {
        return "2. Mettilo nella cartella dei modelli, con il nome " + name + ":";
    }

    // The size in bytes, with Italian thousands: "2.600.224.416".
    function byHandCheck(size: real, sha256: string): string {
        const bytes = size.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        return "3. Premi Riprova: lo controllo. Deve pesare " + bytes + " byte, con sha256 " + sha256 + ".";
    }

    // The tray icon and its list
    readonly property string appName: "Jiffin"
    readonly property string quit: "Esci"
    readonly property string reminders: "Promemoria"
    readonly property string newOne: "Nuovo"
    readonly property string unseen: "Non visti"
    readonly property string active: "Attivi"
    readonly property string noReminders: "Nessun promemoria attivo."
    readonly property string edit: "Modifica"
    readonly property string complete: "Completa"
    readonly property string remove: "Elimina"
    readonly property string removeQuestion: "Eliminare il promemoria per sempre?"
    readonly property string retry: "Riprova"
    readonly property var months: ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    readonly property var browsers: ({
            "vivaldi.exe": "Vivaldi",
            "chrome.exe": "Chrome",
            "brave.exe": "Brave"
        })
    // What the engine's trouble means, by TrayList.Engine; WORKING says nothing.
    readonly property var engineTrouble: ["", "Il modello si è fermato: lo sto riavviando.", "Il modello si è fermato quattro volte in un'ora. Finché non riparte, i promemoria non avvisano.", "Il modello non si carica. Finché non riparte, i promemoria non avvisano.", "La scheda video non ha abbastanza memoria per il modello. Chiudi un'app che la usa, poi riprova.", "Il modello è di un'altra versione di Jiffin: reinstalla l'app."]

    // The sentence the two boxes make (#12): "Quando …, ti ricordo di …", "ti ricordo ogni volta"
    // for a perennial reminder (#84). The full stop comes with the action: Italian puts none after
    // an ellipsis.
    function preview(condition: string, action: string, perennial: bool): string {
        return (condition || "Quando …") + ", ti ricordo " + (perennial ? "ogni volta " : "") + "di " + (action ? action + "." : "…");
    }

    // Under "Quando", for the words of a time not understood (#90): the reminder still saves,
    // without its time. "Non capisco «verso sera» e «a dicembre»: …".
    function notUnderstood(words: list<string>): string {
        const quoted = words.map(word => "«" + word + "»");
        const listed = quoted.length > 1 ? quoted.slice(0, -1).join(", ") + " e " + quoted[quoted.length - 1] : quoted.join("");
        return "Non capisco " + listed + ": suona a qualsiasi ora.";
    }

    // Under the sentence, while a time already over keeps Salva off (#84): "Oggi alle 09:00 …".
    function past(when: string): string {
        return when + " è già passato. Per salvare, scrivi un giorno o un'ora che deve ancora venire.";
    }

    // Under an unseen alert: its condition, and when it appeared.
    function appeared(condition: string, daysAgo: int, day: int, month: int, time: string): string {
        let when = "alle " + time;
        if (daysAgo === 1)
            when = "ieri " + when;
        else if (daysAgo > 1)
            when = ([1, 8, 11].includes(day) ? "l'" : "il ") + day + " " + months[month - 1] + " " + when;
        return condition + ", " + when;
    }

    // Under an active reminder, when useful: its snooze, and the places "Non qui" silenced it in.
    function status(returnsIn: int, returnsAt: string, tomorrow: bool, silences: int): string {
        const parts = [];
        if (returnsIn > 0)
            parts.push("Rimandato: torna tra " + returnsIn + " min");
        else if (returnsAt.length > 0)
            parts.push("Rimandato: torna " + (tomorrow ? "domani " : "") + "alle " + returnsAt);
        if (silences > 0)
            parts.push("Taciuto in " + silences + (silences === 1 ? " posto" : " posti"));
        return parts.join(" · ");
    }

    // The browsers whose address cannot be read, by app: "Chrome e Brave: …".
    function unreadable(apps: list<string>): string {
        const names = apps.map(app => browsers[app] ?? app);
        const listed = names.length > 1 ? names.slice(0, -1).join(", ") + " e " + names[names.length - 1] : names.join("");
        return listed + ": non riesco a leggere l'indirizzo. Uso solo app e titolo.";
    }
}
