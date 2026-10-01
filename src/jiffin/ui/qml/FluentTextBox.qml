// A Fluent 2 text box, drawn by us (ADR-0010): a header over the box, and a description under it
// when there is one. The text wraps and never breaks a line: Enter says the text is done, as in
// a dialog, and Tab moves on. Colours, padding and edges are WinUI's TextBox.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T

FocusScope {
    id: root

    property string header
    property string description
    property alias text: box.text
    property alias placeholderText: box.placeholderText

    signal accepted

    implicitWidth: column.implicitWidth
    implicitHeight: column.implicitHeight

    ColumnLayout {
        id: column

        anchors.fill: parent
        spacing: 0

        Text {
            Layout.fillWidth: true
            Layout.bottomMargin: 8
            text: root.header
            color: Colors.textPrimary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            wrapMode: Text.Wrap
        }

        T.TextArea {
            id: box

            readonly property int lines: 2

            Layout.fillWidth: true
            // At least two lines, as the board shows; longer texts make the box taller.
            implicitHeight: Math.max(contentHeight, lines * Typography.bodyLine) + topPadding + bottomPadding
            // WinUI's padding, 10,5,6,6, inside a 1 px border.
            leftPadding: 11
            topPadding: 6
            rightPadding: 7
            bottomPadding: 7
            focus: true
            activeFocusOnTab: true
            hoverEnabled: true
            wrapMode: TextEdit.Wrap
            color: Colors.textPrimary
            placeholderTextColor: Colors.textSecondary
            font.family: Typography.textFont
            font.pixelSize: Typography.body
            Accessible.name: root.header
            // The selection keeps Qt's colours, which are Windows' accent and its text.

            Keys.onReturnPressed: event => {
                root.accepted();
            }
            Keys.onEnterPressed: event => {
                root.accepted();
            }
            Keys.onTabPressed: event => {
                box.nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason);
            }
            Keys.onBacktabPressed: event => {
                box.nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason);
            }

            // The template draws no placeholder. WinUI's shows while the box is empty, with the
            // focus too.
            Text {
                x: box.leftPadding
                y: box.topPadding
                width: box.width - box.leftPadding - box.rightPadding
                visible: box.length === 0 && box.preeditText.length === 0
                text: box.placeholderText
                color: box.placeholderTextColor
                font: box.font
                wrapMode: Text.Wrap
            }

            background: Rectangle {
                radius: 4
                color: box.activeFocus ? Colors.controlFillInputActive : box.hovered ? Colors.controlFillHover : Colors.controlFill
                border.width: 1
                border.color: Colors.controlStroke

                // The bottom edge: the bottom rows of the rounded box, 1 px strong at rest and
                // 2 px of accent with the focus.
                Item {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: box.activeFocus ? 2 : 1
                    clip: true

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: box.height
                        radius: 4
                        color: box.activeFocus ? Colors.accent : Colors.controlStrongStroke
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.topMargin: 4
            visible: root.description.length > 0
            text: root.description
            color: Colors.textSecondary
            font.family: Typography.captionFont
            font.pixelSize: Typography.caption
            lineHeight: Typography.captionLine
            lineHeightMode: Text.FixedHeight
            wrapMode: Text.Wrap
        }
    }
}
