// The settings window (#43): the material of Jiffin's windows, as four radio buttons. A card like
// the creation window, on the material it sets, with an X on its title's line and no Chiudi, as
// Windows' own Settings (ADR-0010, ADR-0023). A click applies the material at once, as there. It
// takes the focus, on the material in use; Tab moves on, Space chooses, and Esc or the X closes
// it. It drags from any point no control takes.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Jiffin

Window {
    id: window

    required property Preferences preferences

    width: 400
    height: content.implicitHeight + 40
    color: "transparent"
    title: Texts.settings
    // No button in the taskbar, as Windows' own panels: the tray icon's menu brings it back.
    flags: Qt.Tool | Qt.FramelessWindowHint

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
        spacing: 16

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

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Text {
                    Layout.fillWidth: true
                    text: Texts.material
                    color: Colors.textPrimary
                    font.family: Typography.textFont
                    font.pixelSize: Typography.body
                    lineHeight: Typography.bodyLine
                    lineHeightMode: Text.FixedHeight
                }
                Text {
                    Layout.fillWidth: true
                    text: Texts.materialHint
                    color: Colors.textSecondary
                    font.family: Typography.captionFont
                    font.pixelSize: Typography.caption
                    lineHeight: Typography.captionLine
                    lineHeightMode: Text.FixedHeight
                    wrapMode: Text.Wrap
                }
            }
            Repeater {
                id: choices

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

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: window.preferences.close()
    }

    Connections {
        target: window.preferences

        function onOpened(): void {
            for (let index = 0; index < choices.count; ++index) {
                const choice = choices.itemAt(index) as FluentRadioButton;
                if (choice.checked)
                    choice.forceActiveFocus();
            }
        }
    }
}
