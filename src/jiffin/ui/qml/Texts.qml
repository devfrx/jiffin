pragma Singleton

import QtQml

// Every string of the interface, in Italian, in one place (#12).
QtObject {
    // The alert
    readonly property string reminder: "Promemoria"
    readonly property string done: "Fatto"
    readonly property string snooze: "Rimanda"
    readonly property string more: "Altre azioni"
    readonly property string back: "Indietro"
    readonly property string quarterHour: "15 min"
    readonly property string hour: "1 ora"
    readonly property string tomorrow: "Domani"
    readonly property string useful: "Utile"
    readonly property string notHere: "Non qui"

    // The creation window
    readonly property string newReminder: "Nuovo promemoria"
    readonly property string editReminder: "Modifica promemoria"
    readonly property string when: "Quando"
    readonly property string whenHint: "Descrivi dove sei: un'app, un sito, un progetto."
    readonly property string whenExample: "quando lavoro al progetto Rossi"
    readonly property string remindMe: "Ricordami di"
    readonly property string remindMeExample: "aggiornare il changelog"
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

    // The sentence the two boxes make (#12): "Quando …, ti ricordo di …". The full stop comes
    // with the action: Italian puts none after an ellipsis.
    function preview(condition: string, action: string): string {
        return (condition || "Quando …") + ", ti ricordo di " + (action ? action + "." : "…");
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
