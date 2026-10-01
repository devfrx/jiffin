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

    // The sentence the two boxes make (#12): "Quando …, ti ricordo di …".
    function preview(condition: string, action: string): string {
        return (condition || "Quando …") + ", ti ricordo di " + (action || "…") + ".";
    }
}
