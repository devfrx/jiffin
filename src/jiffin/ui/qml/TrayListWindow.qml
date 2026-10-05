// The tray list (#12, #43, #84): what keeps Jiffin from working fully, the model file on its way
// first, the alerts that vanished unanswered, with Fatto and Rimanda, the active reminders, with
// Nuovo, Modifica, Completa and Elimina, and the return pause, with Cambia. A card on the alerts'
// material, over the tray, with an X after Nuovo (ADR-0010, ADR-0023). It takes the focus; Tab
// moves from button to button, and Esc, the X or a click elsewhere closes it. It drags from any
// point no control takes. Rimanda opens the alert's menu, a window of its own.
// Bound: the rows take their data as required properties, and reach the list by its id.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

Window {
    id: window

    required property TrayList trayList
    required property FirstRun firstRun
    required property Preferences preferences
    // Rimanda's menu, for the list to show and hide: a QtObject, since PySide has no converter
    // for the Window type of QML.
    readonly property QtObject menu: snoozeMenu
    // The Rimanda the menu opens from, in the window: taken at each click, as the list scrolls.
    property rect menuButton

    // Scrolls the list to the item Tab has reached.
    function reveal(item: Item): void {
        const top = item.mapToItem(content, 0, 0).y - 8;
        const bottom = top + item.height + 16;
        if (top < scroller.contentY)
            scroller.contentY = Math.max(0, top);
        else if (bottom > scroller.contentY + scroller.height)
            scroller.contentY = Math.min(scroller.contentHeight - scroller.height, bottom - scroller.height);
    }

    // Rimanda on an unseen alert: the menu opens under the button, on its first item when the
    // keyboard reached the button, or closes.
    function toggleMenu(alertId: int, button: T.AbstractButton): void {
        const corner = button.mapToItem(null, 0, 0);
        window.menuButton = Qt.rect(corner.x, corner.y, button.width, button.height);
        snoozeMenu.current = button.visualFocus ? 0 : -1;
        window.trayList.toggleMenu(alertId);
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

    // Any point no control takes moves the window, as a title bar does (ADR-0023).
    Item {
        anchors.fill: parent

        DragHandler {
            target: null
            // Never from a control: Qt's default would take a drag over from the item that
            // got the press, a button too.
            grabPermissions: PointerHandler.CanTakeOverFromHandlersOfDifferentType | PointerHandler.ApprovesTakeOverByAnything
            onActiveChanged: {
                if (active)
                    window.startSystemMove();
            }
        }
    }

    Flickable {
        id: scroller

        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        // The mouse moves the window, as in Windows' own lists: the wheel and the bar scroll.
        acceptedButtons: Qt.NoButton
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
                    spacing: 4

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
                    // The X, as the other windows', 12 px from the edge; never reached by Tab,
                    // since Esc does the same.
                    FluentButton {
                        kind: FluentButton.Subtle
                        glyph: "" // Cancel
                        Accessible.name: Texts.close
                        onClicked: window.trayList.close()
                    }
                }

                // The model file on its way (ADR-0015): the download, or what stopped it.
                FluentInfoBar {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    visible: window.firstRun.waiting
                    severity: window.firstRun.problem ? FluentInfoBar.Error : FluentInfoBar.Informational
                    message: window.firstRun.problem ? Texts.modelTrouble(window.firstRun.stage, window.firstRun.missing) : Texts.downloading(window.firstRun.done, window.firstRun.total, window.firstRun.minutes)

                    FluentProgressBar {
                        Layout.fillWidth: true
                        visible: !window.firstRun.problem
                        value: window.firstRun.total > 0 ? window.firstRun.done / window.firstRun.total : 0
                        Accessible.name: Texts.stepDownload
                    }
                    Row {
                        spacing: 8

                        FluentButton {
                            visible: window.firstRun.problem
                            text: window.firstRun.retrying ? Texts.retrying : Texts.retry
                            enabled: !window.firstRun.retrying
                            focusPolicy: Qt.StrongFocus
                            onClicked: window.trayList.retryModel()
                        }
                        FluentButton {
                            text: Texts.details
                            focusPolicy: Qt.StrongFocus
                            onClicked: window.trayList.details()
                        }
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
                            required property string action
                            required property string line
                            required property bool fresh

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
                                        // Its condition without the time, and when it appeared.
                                        CaptionText {
                                            text: card.line
                                        }
                                    }
                                }
                                Row {
                                    Layout.leftMargin: 17
                                    spacing: 8

                                    FluentButton {
                                        kind: FluentButton.Accent
                                        text: Texts.done
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.done(card.alertId)
                                    }
                                    // The alert's menu (#84), with the same items.
                                    FluentButton {
                                        id: snoozeButton

                                        readonly property bool menuOpen: window.trayList.menuFor === card.alertId

                                        text: Texts.snooze
                                        chevron: true
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.toggleMenu(card.alertId, snoozeButton)
                                        // Tab moving on closes the menu; the window losing the
                                        // focus closes the whole list.
                                        onActiveFocusChanged: {
                                            if (!activeFocus && menuOpen && focusReason !== Qt.ActiveWindowFocusReason)
                                                window.trayList.closeMenu();
                                        }
                                    }
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
                            required property string action
                            required property string remainder
                            required property string when
                            required property bool perennial
                            required property string endedOn
                            required property int returnsIn
                            required property string returnsAt
                            required property bool returnsTomorrow
                            required property int silences
                            readonly property string status: Texts.status(endedOn, returnsIn, returnsAt, returnsTomorrow, silences)
                            // Elimina asks first: the reminder goes for good, with all it knows.
                            property bool confirming: false

                            // The row turns into the question and back; the focus goes along
                            // when it was on the button.
                            function swap(confirming: bool, from: T.AbstractButton, to: T.AbstractButton): void {
                                const focused = from.activeFocus;
                                const reason = from.visualFocus ? Qt.TabFocusReason : Qt.OtherFocusReason;
                                row.confirming = confirming;
                                if (focused)
                                    to.forceActiveFocus(reason);
                            }

                            Layout.fillWidth: true
                            implicitHeight: rowLayout.implicitHeight + 16

                            RowLayout {
                                id: rowLayout

                                x: 8
                                y: 8
                                width: row.width - 8 - 12
                                spacing: 4

                                // Completa: a circle, as in Microsoft To Do; the check shows under
                                // the mouse. A reminder of every time never completes: the arrows
                                // of its alert, an icon (#84). Both keep their place while
                                // Elimina asks.
                                Item {
                                    Layout.alignment: Qt.AlignTop
                                    implicitWidth: 32
                                    implicitHeight: 32

                                    FluentButton {
                                        id: completeButton

                                        visible: !row.perennial
                                        opacity: row.confirming ? 0 : 1
                                        enabled: !row.confirming
                                        kind: FluentButton.Subtle
                                        glyph: completeButton.hovered ? "" : "" // Completed, CircleRing
                                        Accessible.name: Texts.complete
                                        Accessible.description: row.action
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.complete(row.reminderId)
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: row.perennial && !row.confirming
                                        text: "" // RepeatAll
                                        color: Colors.textSecondary
                                        font.family: Typography.iconFont
                                        font.pixelSize: Typography.icon
                                        Accessible.name: Texts.everyTime
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignTop
                                    Layout.topMargin: 6
                                    spacing: 2

                                    BodyText {
                                        text: row.action
                                    }
                                    // The condition without its time: a reminder with only a time
                                    // has none.
                                    CaptionText {
                                        visible: !row.confirming && row.remainder.length > 0
                                        text: row.remainder
                                    }
                                    // The time understood, written for today (ADR-0020).
                                    RowLayout {
                                        Layout.fillWidth: true
                                        visible: !row.confirming && row.when.length > 0
                                        spacing: 6

                                        Text {
                                            Layout.alignment: Qt.AlignTop
                                            Layout.topMargin: 2
                                            text: "" // Clock
                                            color: Colors.textSecondary
                                            font.family: Typography.iconFont
                                            font.pixelSize: Typography.caption
                                        }
                                        CaptionText {
                                            text: row.when
                                        }
                                    }
                                    CaptionText {
                                        visible: !row.confirming && row.status.length > 0
                                        text: row.status
                                    }
                                    CaptionText {
                                        visible: row.confirming
                                        text: Texts.removeQuestion
                                    }
                                    Row {
                                        Layout.topMargin: 6
                                        spacing: 8
                                        visible: row.confirming

                                        FluentButton {
                                            id: keepButton

                                            text: Texts.cancel
                                            Accessible.description: row.action
                                            focusPolicy: Qt.StrongFocus
                                            onClicked: row.swap(false, keepButton, removeButton)
                                        }
                                        FluentButton {
                                            kind: FluentButton.Accent
                                            text: Texts.remove
                                            Accessible.description: row.action
                                            focusPolicy: Qt.StrongFocus
                                            onClicked: window.trayList.delete(row.reminderId)
                                        }
                                    }
                                }
                                FluentButton {
                                    Layout.alignment: Qt.AlignTop
                                    visible: !row.confirming
                                    kind: FluentButton.Subtle
                                    glyph: "" // Edit
                                    Accessible.name: Texts.edit
                                    Accessible.description: row.action
                                    focusPolicy: Qt.StrongFocus
                                    onClicked: window.trayList.edit(row.reminderId)
                                }
                                FluentButton {
                                    id: removeButton

                                    Layout.alignment: Qt.AlignTop
                                    visible: !row.confirming
                                    kind: FluentButton.Subtle
                                    glyph: "" // Delete
                                    Accessible.name: Texts.remove
                                    Accessible.description: row.action
                                    focusPolicy: Qt.StrongFocus
                                    onClicked: row.swap(true, removeButton, keepButton)
                                }
                            }

                            Connections {
                                target: window.trayList

                                function onOpened(): void {
                                    row.confirming = false;
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

                // Where the list ends, after a thin line: the return pause (#84), and Cambia,
                // which opens the settings.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: -4
                    implicitHeight: 1
                    color: Colors.controlStroke
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 16
                    Layout.rightMargin: 12
                    Layout.topMargin: -6
                    spacing: 8

                    CaptionText {
                        Layout.alignment: Qt.AlignVCenter
                        text: Texts.returnsAfter(window.preferences.returnPause)
                    }
                    FluentButton {
                        kind: FluentButton.Subtle
                        text: Texts.change
                        focusPolicy: Qt.StrongFocus
                        onClicked: window.trayList.settings()
                    }
                }
            }
        }
    }

    // While Rimanda's menu is open, a press anywhere in the list closes it and does nothing
    // else, as Windows' light dismiss: the menu never takes the focus, so the list hears it. It
    // keeps the press until the button goes up, so that no drag starts; the wheel closes it too.
    MouseArea {
        id: dismiss

        anchors.fill: parent
        visible: window.trayList.menuFor !== 0 || dismiss.pressed
        acceptedButtons: Qt.AllButtons
        onPressed: window.trayList.closeMenu()
        onWheel: window.trayList.closeMenu()
    }

    // Esc closes the menu first.
    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: {
            if (window.trayList.menuFor !== 0)
                window.trayList.closeMenu();
            else
                window.trayList.close();
        }
    }
    // While the menu is open its Rimanda keeps the focus, and these keys go to the menu before
    // the button, as in Windows' menus: Up and Down move over its items, and Space or Enter
    // pick one. Before a key moves, Space and Enter are a click on Rimanda, which closes it.
    Shortcut {
        sequences: ["Down"]
        enabled: window.trayList.menuFor !== 0
        onActivated: snoozeMenu.move(1)
    }
    Shortcut {
        sequences: ["Up"]
        enabled: window.trayList.menuFor !== 0
        onActivated: snoozeMenu.move(-1)
    }
    Shortcut {
        sequences: ["Space", "Return", "Enter"]
        enabled: window.trayList.menuFor !== 0 && snoozeMenu.current >= 0
        onActivated: snoozeMenu.trigger()
    }

    // Under its Rimanda, on its left edge and 4 px down, as Windows' menus; over it, 4 px up,
    // where the work area would end first.
    AlertMenu {
        id: snoozeMenu

        readonly property real below: window.y + window.menuButton.y + window.menuButton.height + 4

        nextTime: window.trayList.nextTime
        x: window.x + Math.round(window.menuButton.x)
        y: Math.round(below + height <= window.trayList.areaBottom ? below : window.y + window.menuButton.y - 4 - height)
        onSnoozeNextTime: window.trayList.snoozeNextTime()
        onSnoozeQuarterHour: window.trayList.snoozeQuarterHour()
        onSnoozeHour: window.trayList.snoozeHour()
        onSnoozeTomorrow: window.trayList.snoozeTomorrow()
        onNotHere: window.trayList.notHere()
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

    // A condition, a time or a status line.
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
