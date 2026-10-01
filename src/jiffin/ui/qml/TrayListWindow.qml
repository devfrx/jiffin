// The tray list (#12, #43): what keeps Jiffin from working fully, the alerts that vanished
// unanswered, with Fatto and Rimanda, and the active reminders, with Nuovo, Modifica, Completa
// and Elimina. A card on the alerts' material, over the tray (ADR-0010). It takes the focus;
// Tab moves from button to button, and Esc or a click elsewhere closes it.
// Bound: the rows take their data as required properties, and reach the list by its id.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

Window {
    id: window

    required property TrayList trayList

    // Scrolls the list to the item Tab has reached.
    function reveal(item: Item): void {
        const top = item.mapToItem(content, 0, 0).y - 8;
        const bottom = top + item.height + 16;
        if (top < scroller.contentY)
            scroller.contentY = Math.max(0, top);
        else if (bottom > scroller.contentY + scroller.height)
            scroller.contentY = Math.min(scroller.contentHeight - scroller.height, bottom - scroller.height);
    }

    width: 368
    height: trayList.maxHeight > 0 ? Math.min(content.implicitHeight, trayList.maxHeight) : content.implicitHeight
    color: "transparent"
    title: Texts.reminders
    // No button in the taskbar, as Windows' own flyouts.
    flags: Qt.Tool | Qt.FramelessWindowHint

    onActiveChanged: {
        if (!active)
            window.trayList.deactivated();
    }
    onActiveFocusItemChanged: {
        if (activeFocusItem !== null && activeFocusItem !== content)
            window.reveal(activeFocusItem);
    }

    // As the alert: without glass, the surface is painted here; with material B, a veil goes
    // over the glass.
    Rectangle {
        anchors.fill: parent
        visible: Look.solid
        color: Colors.surface
    }
    Rectangle {
        anchors.fill: parent
        visible: Look.veilOpacity > 0
        color: Colors.veil
        opacity: Look.veilOpacity
    }

    Flickable {
        id: scroller

        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        T.ScrollBar.vertical: FluentScrollBar {}

        FocusScope {
            id: content

            width: scroller.width
            implicitHeight: column.implicitHeight + 16 + 12
            focus: true

            ColumnLayout {
                id: column

                y: 16
                width: parent.width
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 16
                    Layout.rightMargin: 12

                    Text {
                        Layout.fillWidth: true
                        text: Texts.reminders
                        color: Colors.textPrimary
                        font.family: Typography.textFont
                        font.pixelSize: Typography.body
                        font.weight: Font.DemiBold
                    }
                    FluentButton {
                        glyph: "" // Add
                        text: Texts.newOne
                        focusPolicy: Qt.StrongFocus
                        onClicked: window.trayList.new()
                    }
                }

                FluentInfoBar {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    visible: window.trayList.engine !== TrayList.WORKING
                    severity: window.trayList.engine === TrayList.RESTARTING ? FluentInfoBar.Warning : FluentInfoBar.Error
                    message: Texts.engineTrouble[window.trayList.engine]
                    // Restarting needs no hand, and Riprova cannot mend another version.
                    action: [TrayList.RESTARTING, TrayList.MISMATCH].includes(window.trayList.engine) ? "" : Texts.retry
                    onTriggered: window.trayList.retry()
                }
                FluentInfoBar {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    visible: window.trayList.unreadable.length > 0
                    message: Texts.unreadable(window.trayList.unreadable)
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    visible: unseenCards.count > 0

                    SectionLabel {
                        text: Texts.unseen
                    }
                    Repeater {
                        id: unseenCards

                        model: window.trayList.unseen

                        delegate: Rectangle {
                            id: card

                            required property int alertId
                            required property string condition
                            required property string action
                            required property bool fresh
                            required property int daysAgo
                            required property int day
                            required property int month
                            required property string time
                            property bool snoozing: false

                            // Rimanda opens its choices in the card, and Indietro closes them;
                            // the focus goes along when it was on the button.
                            function swap(snoozing: bool, from: T.AbstractButton, to: T.AbstractButton): void {
                                const focused = from.activeFocus;
                                const reason = from.visualFocus ? Qt.TabFocusReason : Qt.OtherFocusReason;
                                card.snoozing = snoozing;
                                if (focused)
                                    to.forceActiveFocus(reason);
                            }

                            Layout.fillWidth: true
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            implicitHeight: cardColumn.implicitHeight + 20
                            radius: 4
                            color: Colors.cardFill

                            ColumnLayout {
                                id: cardColumn

                                x: 8
                                y: 10
                                width: card.width - 16
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 10

                                    // New to the list since it opened.
                                    Rectangle {
                                        Layout.alignment: Qt.AlignTop
                                        Layout.topMargin: 6
                                        implicitWidth: 7
                                        implicitHeight: 7
                                        radius: 3.5
                                        color: card.fresh ? Colors.accent : "transparent"
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2

                                        BodyText {
                                            text: card.action
                                        }
                                        CaptionText {
                                            text: Texts.appeared(card.condition, card.daysAgo, card.day, card.month, card.time)
                                        }
                                    }
                                }
                                Row {
                                    Layout.leftMargin: 17
                                    spacing: 8
                                    visible: !card.snoozing

                                    FluentButton {
                                        kind: FluentButton.Accent
                                        text: Texts.done
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.done(card.alertId)
                                    }
                                    FluentButton {
                                        id: snoozeButton

                                        text: Texts.snooze
                                        chevron: true
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: card.swap(true, snoozeButton, backButton)
                                    }
                                }
                                Row {
                                    Layout.leftMargin: 17
                                    spacing: 8
                                    visible: card.snoozing

                                    FluentButton {
                                        id: backButton

                                        kind: FluentButton.Subtle
                                        glyph: "" // Back
                                        Accessible.name: Texts.back
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: card.swap(false, backButton, snoozeButton)
                                    }
                                    FluentButton {
                                        text: Texts.quarterHour
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.snoozeQuarterHour(card.alertId)
                                    }
                                    FluentButton {
                                        text: Texts.hour
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.snoozeHour(card.alertId)
                                    }
                                    FluentButton {
                                        text: Texts.tomorrow
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.snoozeTomorrow(card.alertId)
                                    }
                                }
                            }

                            Connections {
                                target: window.trayList

                                function onOpened(): void {
                                    card.snoozing = false;
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    SectionLabel {
                        Layout.bottomMargin: 2
                        text: Texts.active
                    }
                    Repeater {
                        id: activeRows

                        model: window.trayList.active

                        delegate: Item {
                            id: row

                            required property int reminderId
                            required property string condition
                            required property string action
                            required property int returnsIn
                            required property string returnsAt
                            required property bool returnsTomorrow
                            required property int silences
                            readonly property string status: Texts.status(returnsIn, returnsAt, returnsTomorrow, silences)

                            Layout.fillWidth: true
                            implicitHeight: rowLayout.implicitHeight + 16

                            RowLayout {
                                id: rowLayout

                                x: 16
                                y: 8
                                width: row.width - 16 - 12
                                spacing: 4

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignTop
                                    spacing: 2

                                    BodyText {
                                        text: row.action
                                    }
                                    CaptionText {
                                        text: row.condition
                                    }
                                    CaptionText {
                                        visible: row.status.length > 0
                                        text: row.status
                                    }
                                }
                                FluentButton {
                                    Layout.alignment: Qt.AlignTop
                                    kind: FluentButton.Subtle
                                    glyph: "" // Edit
                                    Accessible.name: Texts.edit
                                    Accessible.description: row.action
                                    focusPolicy: Qt.StrongFocus
                                    onClicked: window.trayList.edit(row.reminderId)
                                }
                                FluentButton {
                                    Layout.alignment: Qt.AlignTop
                                    kind: FluentButton.Subtle
                                    glyph: "" // CheckMark
                                    Accessible.name: Texts.complete
                                    Accessible.description: row.action
                                    focusPolicy: Qt.StrongFocus
                                    onClicked: window.trayList.complete(row.reminderId)
                                }
                                FluentButton {
                                    Layout.alignment: Qt.AlignTop
                                    kind: FluentButton.Subtle
                                    glyph: "" // Delete
                                    Accessible.name: Texts.remove
                                    Accessible.description: row.action
                                    focusPolicy: Qt.StrongFocus
                                    onClicked: window.trayList.delete(row.reminderId)
                                }
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 6
                        Layout.bottomMargin: 6
                        visible: activeRows.count === 0
                        text: Texts.noReminders
                        color: Colors.textSecondary
                        font.family: Typography.textFont
                        font.pixelSize: Typography.body
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: window.trayList.close()
    }

    // A section's name: "Non visti", "Attivi".
    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.leftMargin: 16
        Layout.rightMargin: 16
        color: Colors.textSecondary
        font.family: Typography.captionFont
        font.pixelSize: Typography.caption
        font.weight: Font.DemiBold
        lineHeight: Typography.captionLine
        lineHeightMode: Text.FixedHeight
    }

    // What to do, on up to two lines.
    component BodyText: Text {
        Layout.fillWidth: true
        color: Colors.textPrimary
        font.family: Typography.textFont
        font.pixelSize: Typography.body
        lineHeight: Typography.bodyLine
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }

    // A condition or a status line.
    component CaptionText: Text {
        Layout.fillWidth: true
        color: Colors.textSecondary
        font.family: Typography.captionFont
        font.pixelSize: Typography.caption
        lineHeight: Typography.captionLine
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
    }
}
