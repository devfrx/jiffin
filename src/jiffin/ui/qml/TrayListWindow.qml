// The tray list (#12, #43, #84): the row of Remind here, what keeps Jiffin from working fully, the
// model file on its way first, the alerts that vanished unanswered, with Done and Snooze, the
// active reminders, with New, Edit, Complete and Delete and what each learned, the completed
// ones, with Reopen and Delete, and the return pause, with Change. A card on the alerts'
// material, over the tray, with an X after New (ADR-0010, ADR-0023). It takes the focus; Tab
// moves from button to button, and Esc, the X or a click elsewhere closes it. It drags from any
// point no control takes. Snooze opens the alert's menu, a window of its own. An unseen alert's
// answer waits 5 s on its card, with Undo, as on the alert (ADR-0030).
// Bound: the rows take their data as required properties, and reach the list by its id.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import Jiffin

Window {
    id: window

    required property TrayList trayList
    required property RemindHere remindHere
    required property FirstRun firstRun
    required property Preferences preferences
    // Snooze's menu, for the list to show and hide: a QtObject, since PySide has no converter
    // for the Window type of QML.
    readonly property QtObject menu: snoozeMenu
    // The Snooze the menu opens from, in the window: taken at each click, as the list scrolls.
    property rect menuButton
    // How long an unseen alert's answer waits with Undo, as on the alert (ADR-0030).
    property int holdDuration: 5000

    // Scrolls the list to the item Tab has reached.
    function reveal(item: Item): void {
        const top = item.mapToItem(content, 0, 0).y - 8;
        const bottom = top + item.height + 16;
        if (top < scroller.contentY)
            scroller.contentY = Math.max(0, top);
        else if (bottom > scroller.contentY + scroller.height)
            scroller.contentY = Math.min(scroller.contentHeight - scroller.height, bottom - scroller.height);
    }

    // Snooze on an unseen alert: the menu opens under the button, on its first item when the
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

                // Remind here (ADR-0029): the card Win+Shift+Q opens, for the last place Jiffin
                // judged, written under it.
                T.AbstractButton {
                    id: remindHereRow

                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    Layout.topMargin: -4
                    implicitHeight: implicitContentHeight + topPadding + bottomPadding
                    leftPadding: 8
                    rightPadding: 10
                    topPadding: 6
                    bottomPadding: 7
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    Accessible.name: Texts.remindHere
                    Accessible.description: window.remindHere.place
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    onClicked: window.trayList.remindHere()

                    background: Rectangle {
                        radius: 4
                        color: remindHereRow.down ? Colors.subtleFillPressed : remindHereRow.hovered ? Colors.subtleFillHover : Colors.cardFill

                        // The focus ring, 3 px outside, as a button's.
                        Rectangle {
                            visible: remindHereRow.visualFocus
                            anchors.fill: parent
                            anchors.margins: -3
                            radius: 7
                            color: "transparent"
                            border.width: 2
                            border.color: Colors.focusStrokeOuter

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 2
                                radius: 5
                                color: "transparent"
                                border.width: 1
                                border.color: Colors.focusStrokeInner
                            }
                        }
                    }
                    contentItem: RowLayout {
                        spacing: 10

                        Text {
                            Layout.alignment: Qt.AlignVCenter
                            text: "" // Ringer
                            color: Colors.textPrimary
                            font.family: Typography.iconFont
                            font.pixelSize: Typography.icon
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Text {
                                Layout.fillWidth: true
                                text: Texts.remindHere
                                color: Colors.textPrimary
                                font.family: Typography.textFont
                                font.pixelSize: Typography.body
                                lineHeight: Typography.bodyLine
                                lineHeightMode: Text.FixedHeight
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: window.remindHere.place.length > 0
                                text: window.remindHere.place
                                color: Colors.textSecondary
                                font.family: Typography.captionFont
                                font.pixelSize: Typography.caption
                                lineHeight: Typography.captionLine
                                lineHeightMode: Text.FixedHeight
                                elide: Text.ElideRight
                                maximumLineCount: 1
                            }
                        }
                        Text {
                            Layout.alignment: Qt.AlignVCenter
                            text: "" // ChevronRight
                            color: Colors.textSecondary
                            font.family: Typography.iconFont
                            font.pixelSize: Typography.chevron
                        }
                    }
                }

                // The pause from the tray (ADR-0024), until it ends or Resume.
                FluentInfoBar {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    visible: window.trayList.pausedAt.length > 0
                    severity: FluentInfoBar.Informational
                    message: Texts.pausedUntil(window.trayList.pausedAt, window.trayList.pausedTomorrow)
                    action: Texts.resume
                    onTriggered: window.trayList.resume()
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
                    // Restarting needs no hand, and Retry cannot mend another version.
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
                            // The answer waiting with Undo, by its name; empty when none.
                            required property string held
                            property real progress: 1

                            // The 5 s start, or stop with Undo. The keyboard's focus goes over
                            // from Done or Snooze to Undo, and back to Done, with its ring when
                            // Tab brought it there.
                            onHeldChanged: {
                                const waits = card.held.length > 0;
                                const from = waits ? (doneButton.activeFocus ? doneButton : snoozeButton) : undoButton;
                                if (waits)
                                    waiting.restart();
                                else
                                    waiting.stop();
                                if (from.activeFocus)
                                    (waits ? undoButton : doneButton).forceActiveFocus(from.visualFocus ? Qt.TabFocusReason : Qt.OtherFocusReason);
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
                                        // Its condition without the time, and when it appeared.
                                        CaptionText {
                                            text: card.line
                                        }
                                    }
                                }
                                Row {
                                    Layout.leftMargin: 17
                                    visible: card.held.length === 0
                                    spacing: 8

                                    FluentButton {
                                        id: doneButton

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
                                // The answer waiting, and Undo, in place of the buttons.
                                Row {
                                    Layout.leftMargin: 17
                                    visible: card.held.length > 0
                                    spacing: 12

                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: card.held
                                        color: Colors.textSecondary
                                        font.family: Typography.textFont
                                        font.pixelSize: Typography.body
                                    }
                                    FluentButton {
                                        id: undoButton

                                        text: Texts.cancel
                                        Accessible.description: card.action
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.undo(card.alertId)
                                    }
                                }
                            }

                            // The 5 s of the answer waiting, on the card's lower edge, clear of
                            // its rounded corners; then the answer goes.
                            Rectangle {
                                x: card.radius
                                anchors.bottom: parent.bottom
                                visible: card.held.length > 0
                                width: (card.width - 2 * card.radius) * card.progress
                                height: 2
                                color: Colors.accent
                            }
                            NumberAnimation {
                                id: waiting

                                target: card
                                property: "progress"
                                from: 1
                                to: 0
                                duration: window.holdDuration
                                onFinished: window.trayList.release(card.alertId)
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
                            // Its situations, each on its line: [{situation, value, line}].
                            required property var situations
                            required property string when
                            required property bool perennial
                            required property string endedOn
                            required property int returnsIn
                            required property string returnsAt
                            required property bool returnsTomorrow
                            required property int silences
                            required property int requests
                            required property bool attentive
                            // The places of its answers, the last answered first: [{line, requested}].
                            required property var places
                            readonly property string status: Texts.status(endedOn, returnsIn, returnsAt, returnsTomorrow)
                            readonly property string learned: Texts.learned(silences, requests, attentive)
                            // Delete asks first: the reminder goes for good, with all it knows.
                            property bool confirming: false
                            // What it learned opens its places, under it.
                            property bool placesOpen: false

                            onLearnedChanged: {
                                if (learned.length === 0)
                                    row.placesOpen = false;
                            }

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

                                // Complete: a circle, as in Microsoft To Do; the check shows under
                                // the mouse. A reminder of every time never completes: the arrows
                                // of its alert, an icon (#84). Both keep their place while
                                // Delete asks.
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
                                    // The condition without its time and its situations: a reminder
                                    // with only a time or situations has none.
                                    CaptionText {
                                        visible: !row.confirming && row.remainder.length > 0
                                        text: row.remainder
                                    }
                                    // Each situation understood, beside its icon (ADR-0028).
                                    Repeater {
                                        model: row.confirming ? [] : row.situations

                                        RowLayout {
                                            id: situationRow

                                            required property var modelData

                                            Layout.fillWidth: true
                                            spacing: 6

                                            SituationIcon {
                                                Layout.alignment: Qt.AlignTop
                                                Layout.topMargin: 2
                                                situation: situationRow.modelData.situation
                                                value: situationRow.modelData.value
                                                color: Colors.textSecondary
                                                font.pixelSize: Typography.caption
                                            }
                                            CaptionText {
                                                text: situationRow.modelData.line
                                            }
                                        }
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
                                    // What it learned (ADR-0029): a click opens its places.
                                    T.AbstractButton {
                                        id: learnedButton

                                        Layout.fillWidth: true
                                        visible: !row.confirming && row.learned.length > 0
                                        implicitHeight: implicitContentHeight
                                        hoverEnabled: true
                                        focusPolicy: Qt.StrongFocus
                                        Accessible.name: row.learned
                                        Accessible.description: row.action
                                        Keys.onReturnPressed: click()
                                        Keys.onEnterPressed: click()
                                        onClicked: row.placesOpen = !row.placesOpen

                                        background: Rectangle {
                                            visible: learnedButton.visualFocus
                                            anchors.fill: parent
                                            anchors.margins: -3
                                            radius: 5
                                            color: "transparent"
                                            border.width: 2
                                            border.color: Colors.focusStrokeOuter

                                            Rectangle {
                                                anchors.fill: parent
                                                anchors.margins: 2
                                                radius: 3
                                                color: "transparent"
                                                border.width: 1
                                                border.color: Colors.focusStrokeInner
                                            }
                                        }
                                        contentItem: RowLayout {
                                            spacing: 4

                                            Text {
                                                Layout.fillWidth: true
                                                text: row.learned
                                                color: learnedButton.hovered ? Colors.textPrimary : Colors.textSecondary
                                                font.family: Typography.captionFont
                                                font.pixelSize: Typography.caption
                                                font.underline: learnedButton.hovered
                                                lineHeight: Typography.captionLine
                                                lineHeightMode: Text.FixedHeight
                                                wrapMode: Text.Wrap
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignTop
                                                Layout.topMargin: 3
                                                text: row.placesOpen ? "" : "" // ChevronUp, ChevronDown
                                                color: Colors.textSecondary
                                                font.family: Typography.iconFont
                                                font.pixelSize: 10
                                            }
                                        }
                                    }
                                    // The places, each with its icon and its X, which forgets it;
                                    // then Forget all.
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        visible: !row.confirming && row.placesOpen
                                        spacing: 0

                                        Repeater {
                                            model: row.places

                                            delegate: RowLayout {
                                                id: placeRow

                                                required property var modelData
                                                required property int index

                                                Layout.fillWidth: true
                                                spacing: 6

                                                Text {
                                                    Layout.alignment: Qt.AlignVCenter
                                                    text: placeRow.modelData.requested ? "" : "" // Ringer, RingerSilent
                                                    color: Colors.textSecondary
                                                    font.family: Typography.iconFont
                                                    font.pixelSize: Typography.caption
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    Layout.alignment: Qt.AlignVCenter
                                                    text: placeRow.modelData.line
                                                    color: Colors.textSecondary
                                                    font.family: Typography.captionFont
                                                    font.pixelSize: Typography.caption
                                                    elide: Text.ElideRight
                                                    maximumLineCount: 1
                                                }
                                                FluentButton {
                                                    kind: FluentButton.Subtle
                                                    glyph: "" // Cancel
                                                    Accessible.name: Texts.forget
                                                    Accessible.description: placeRow.modelData.line
                                                    focusPolicy: Qt.StrongFocus
                                                    onClicked: window.trayList.forget(row.reminderId, placeRow.index)
                                                }
                                            }
                                        }
                                        FluentButton {
                                            Layout.leftMargin: -12
                                            kind: FluentButton.Subtle
                                            text: Texts.forgetAll
                                            Accessible.description: row.action
                                            focusPolicy: Qt.StrongFocus
                                            onClicked: window.trayList.forgetAll(row.reminderId)
                                        }
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
                                    row.placesOpen = false;
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

                // The completed reminders (ADR-0030): a row with how many, closed each time the
                // list opens; open, the most recently completed first.
                ColumnLayout {
                    id: completedSection

                    property bool open: false

                    Layout.fillWidth: true
                    Layout.topMargin: -6
                    spacing: 2
                    visible: completedRows.count > 0

                    T.AbstractButton {
                        id: completedHeader

                        Layout.fillWidth: true
                        Layout.leftMargin: 8
                        Layout.rightMargin: 8
                        implicitHeight: implicitContentHeight + topPadding + bottomPadding
                        leftPadding: 8
                        rightPadding: 8
                        topPadding: 5
                        bottomPadding: 5
                        hoverEnabled: true
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: Texts.completed(completedRows.count)
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        onClicked: completedSection.open = !completedSection.open

                        background: Rectangle {
                            radius: 4
                            color: completedHeader.down ? Colors.subtleFillPressed : completedHeader.hovered ? Colors.subtleFillHover : "transparent"

                            // The focus ring, 3 px outside, as a button's.
                            Rectangle {
                                visible: completedHeader.visualFocus
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: 7
                                color: "transparent"
                                border.width: 2
                                border.color: Colors.focusStrokeOuter

                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    radius: 5
                                    color: "transparent"
                                    border.width: 1
                                    border.color: Colors.focusStrokeInner
                                }
                            }
                        }
                        contentItem: RowLayout {
                            spacing: 8

                            Text {
                                Layout.alignment: Qt.AlignVCenter
                                text: completedSection.open ? "" : "" // ChevronDown, ChevronRight
                                color: Colors.textSecondary
                                font.family: Typography.iconFont
                                font.pixelSize: 10
                            }
                            Text {
                                Layout.fillWidth: true
                                text: Texts.completed(completedRows.count)
                                color: Colors.textSecondary
                                font.family: Typography.captionFont
                                font.pixelSize: Typography.caption
                                font.weight: Font.DemiBold
                                lineHeight: Typography.captionLine
                                lineHeightMode: Text.FixedHeight
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: completedSection.open
                        spacing: 2

                        Repeater {
                            id: completedRows

                            model: window.trayList.completed

                            delegate: Item {
                                id: completedRow

                                required property int reminderId
                                required property string action
                                required property string line
                                // Delete asks first, as among the active.
                                property bool confirming: false

                                // The row turns into the question and back; the focus goes along
                                // when it was on the button.
                                function swap(confirming: bool, from: T.AbstractButton, to: T.AbstractButton): void {
                                    const focused = from.activeFocus;
                                    const reason = from.visualFocus ? Qt.TabFocusReason : Qt.OtherFocusReason;
                                    completedRow.confirming = confirming;
                                    if (focused)
                                        to.forceActiveFocus(reason);
                                }

                                Layout.fillWidth: true
                                implicitHeight: completedLayout.implicitHeight + 16

                                RowLayout {
                                    id: completedLayout

                                    x: 8
                                    y: 8
                                    width: completedRow.width - 8 - 12
                                    spacing: 4

                                    // The full circle in the accent colour, as in Microsoft To Do:
                                    // Reopen. It keeps its place while Delete asks.
                                    FluentButton {
                                        Layout.alignment: Qt.AlignTop
                                        opacity: completedRow.confirming ? 0 : 1
                                        enabled: !completedRow.confirming
                                        kind: FluentButton.Subtle
                                        glyph: "" // CompletedSolid
                                        glyphColor: Colors.accent
                                        Accessible.name: Texts.reopen
                                        Accessible.description: completedRow.action
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: window.trayList.reopen(completedRow.reminderId)
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignTop
                                        Layout.topMargin: 6
                                        spacing: 2

                                        // Struck through and grey: done (ADR-0030).
                                        BodyText {
                                            text: completedRow.action
                                            color: Colors.textSecondary
                                            font.strikeout: true
                                        }
                                        // The condition without its time, and when it was
                                        // completed.
                                        CaptionText {
                                            visible: !completedRow.confirming
                                            text: completedRow.line
                                        }
                                        CaptionText {
                                            visible: completedRow.confirming
                                            text: Texts.removeQuestion
                                        }
                                        Row {
                                            Layout.topMargin: 6
                                            spacing: 8
                                            visible: completedRow.confirming

                                            FluentButton {
                                                id: keepCompleted

                                                text: Texts.cancel
                                                Accessible.description: completedRow.action
                                                focusPolicy: Qt.StrongFocus
                                                onClicked: completedRow.swap(false, keepCompleted, removeCompleted)
                                            }
                                            FluentButton {
                                                kind: FluentButton.Accent
                                                text: Texts.remove
                                                Accessible.description: completedRow.action
                                                focusPolicy: Qt.StrongFocus
                                                onClicked: window.trayList.delete(completedRow.reminderId)
                                            }
                                        }
                                    }
                                    FluentButton {
                                        id: removeCompleted

                                        Layout.alignment: Qt.AlignTop
                                        visible: !completedRow.confirming
                                        kind: FluentButton.Subtle
                                        glyph: "" // Delete
                                        Accessible.name: Texts.remove
                                        Accessible.description: completedRow.action
                                        focusPolicy: Qt.StrongFocus
                                        onClicked: completedRow.swap(true, removeCompleted, keepCompleted)
                                    }
                                }

                                Connections {
                                    target: window.trayList

                                    function onOpened(): void {
                                        completedRow.confirming = false;
                                    }
                                }
                            }
                        }
                    }

                    Connections {
                        target: window.trayList

                        function onOpened(): void {
                            completedSection.open = false;
                        }
                    }
                }

                // Where the list ends, after a thin line: the return pause (#84), and Change,
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

    // While Snooze's menu is open, a press anywhere in the list closes it and does nothing
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
    // While the menu is open its Snooze keeps the focus, and these keys go to the menu before
    // the button, as in Windows' menus: Up and Down move over its items, and Space or Enter
    // pick one. Before a key moves, Space and Enter are a click on Snooze, which closes it.
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

    // Under its Snooze, on its left edge and 4 px down, as Windows' menus; over it, 4 px up,
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
