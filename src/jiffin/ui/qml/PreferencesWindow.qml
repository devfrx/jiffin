// The settings window (#43, #84, #153): the return pause, a number and its unit, then the network
// in use, home, the office or neither, then the material of Jiffin's windows, as radio buttons. A
// card like the creation window, on the material it sets, with an X on its title's line and no
// Close, as Windows' own Settings (ADR-0010, ADR-0023). A change applies at once, as there. It
// takes the focus, on the pause; Tab moves on, Space chooses, and Esc or the X closes it. It drags
// from any point no control takes.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property Preferences preferences
    required property Networks networks
    // The unit's list, for the settings to show with the glass: a QtObject, since PySide has no
    // converter for the Window type of QML.
    readonly property QtObject units: unitBox.list

    width: 400
    height: content.implicitHeight + 40
    color: "transparent"
    title: Texts.settings
    // No button in the taskbar, as Windows' own panels: the tray icon's menu brings it back.
    flags: Qt.Tool | Qt.FramelessWindowHint

    // A click in another window closes the unit's list, which belongs to this one: a window
    // stays active while its list has the focus.
    onActiveChanged: {
        if (!active)
            window.preferences.closeUnits();
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

    ColumnLayout {
        id: content

        x: 24
        y: 20
        width: window.width - 48
        spacing: 20

        Text {
            id: title

            Layout.fillWidth: true
            // Clear of the X.
            Layout.rightMargin: 32
            text: window.title
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            font.weight: Font.DemiBold
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
        }

        // The return pause (ADR-0021), as a number and its unit; changing the unit converts it.
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            Heading {
                title: Texts.returnPause
                hint: Texts.returnPauseHint
            }
            Row {
                spacing: 8

                FluentNumberBox {
                    id: pauseBox

                    accessibleName: Texts.returnPause
                    value: window.preferences.pauseValue
                    from: window.preferences.pauseFrom
                    to: window.preferences.pauseTo
                    onEdited: value => window.preferences.setPause(value)
                }
                FluentComboBox {
                    id: unitBox

                    model: Texts.units
                    currentIndex: window.preferences.minutes ? 1 : 0
                    open: window.preferences.unitsOpen
                    Accessible.name: Texts.unit
                    onClicked: window.preferences.toggleUnits()
                    onActivated: index => window.preferences.setMinutes(index === 1)
                    onDismissed: window.preferences.closeUnits()
                }
            }
        }

        // The network in use (ADR-0028): home, the office or neither, for the reminders "a casa"
        // and "in ufficio"; the check follows the label, never the click. Without a network, a
        // line says so.
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            Heading {
                title: Texts.network
                hint: Texts.networkHint
            }
            Repeater {
                model: window.networks.connected ? ["home", "office", ""] : []

                delegate: FluentRadioButton {
                    required property string modelData

                    Layout.fillWidth: true
                    text: Texts.networkLabels[modelData]
                    checkable: false
                    checked: window.networks.label === modelData
                    onClicked: window.networks.labelInUse(modelData)
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !window.networks.connected
                text: Texts.offline
                color: Colors.textSecondary
                font.family: Typography.textFont
                font.pixelSize: Typography.body
                lineHeight: Typography.bodyLine
                lineHeightMode: Text.FixedHeight
                wrapMode: Text.Wrap
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            Heading {
                title: Texts.material
                hint: Texts.materialHint
            }
            Repeater {
                model: window.preferences.materials

                // The check follows the look, never the click: the click asks for the material,
                // and the look says which one is in use.
                delegate: FluentRadioButton {
                    required property string modelData

                    Layout.fillWidth: true
                    text: Texts.materials[modelData][0]
                    description: Texts.materials[modelData][1]
                    checkable: false
                    checked: window.preferences.material === modelData
                    onClicked: window.preferences.choose(modelData)
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: Look.solid
            text: Texts.solidSurfaces
            color: Colors.textSecondary
            font.family: Typography.captionFont
            font.pixelSize: Typography.caption
            lineHeight: Typography.captionLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
    }

    // The X, as the creation window's: on the title's line, 12 px from the edge, never reached
    // by Tab, since Esc does the same.
    FluentButton {
        x: window.width - 12 - width
        y: content.y + title.y + (title.height - height) / 2
        kind: FluentButton.Subtle
        glyph: "" // Cancel
        Accessible.name: Texts.close
        onClicked: window.preferences.close()
    }

    // While the unit's list is open, a press anywhere in the window closes it and does nothing
    // else, as Windows' light dismiss: the list never takes the focus, so the window hears it.
    // It keeps the press until the button goes up, so that no drag starts.
    MouseArea {
        id: dismiss

        anchors.fill: parent
        visible: window.preferences.unitsOpen || dismiss.pressed
        acceptedButtons: Qt.AllButtons
        onPressed: window.preferences.closeUnits()
        onWheel: window.preferences.closeUnits()
    }

    // Esc closes the unit's list first.
    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: {
            if (window.preferences.unitsOpen)
                window.preferences.closeUnits();
            else
                window.preferences.close();
        }
    }

    Connections {
        target: window.preferences

        function onOpened(): void {
            pauseBox.forceActiveFocus();
        }
    }

    // A setting's name, with what it does under it.
    component Heading: ColumnLayout {
        id: heading

        property string title
        property string hint

        Layout.fillWidth: true
        spacing: 0

        Text {
            Layout.fillWidth: true
            text: heading.title
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            lineHeight: Typography.bodyLine
            lineHeightMode: Text.FixedHeight
        }
        Text {
            Layout.fillWidth: true
            text: heading.hint
            color: Colors.textSecondary
            font.family: Typography.captionFont
            font.pixelSize: Typography.caption
            lineHeight: Typography.captionLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
    }
}
