// A Fluent 2 number box, drawn by us (ADR-0010), as WinUI's NumberBox with its spin buttons
// inline (NumberBox.xaml, microsoft-ui-xaml at 8463f45162): a one-line text box with Up (E70E)
// and Down (E70D) inside on the right, 32 px wide, glyphs at 12 px, 4 px from the edges, off at
// the ends of the range. The buttons repeat while held; Up and Down on the keyboard step too. A
// number out of range goes back within it when the box is left or Enter is pressed, as NumberBox
// does. `edited` gives the new number, and whoever holds the value sets it.
import QtQuick
import QtQuick.Templates as T

FocusScope {
    id: root

    property int value
    property int from
    property int to
    property string accessibleName

    signal edited(int value)

    // Within the range; the box shows the value again, changed or not.
    function set(wanted: int): void {
        const number = Math.max(root.from, Math.min(root.to, wanted));
        if (number !== root.value)
            root.edited(number);
        box.text = String(root.value);
    }

    implicitWidth: 120
    implicitHeight: 32
    onValueChanged: box.text = String(root.value)
    Component.onCompleted: box.text = String(root.value)

    T.TextField {
        id: box

        anchors.fill: parent
        // WinUI's padding, 10,5,6,6 inside a 1 px border, and room for the buttons.
        leftPadding: 11
        topPadding: 6
        rightPadding: 4 + 32 + 4 + 32 + 4
        bottomPadding: 7
        focus: true
        hoverEnabled: true
        inputMethodHints: Qt.ImhDigitsOnly
        color: Colors.textPrimary
        font.family: Typography.textFont
        font.pixelSize: Typography.body
        verticalAlignment: TextInput.AlignVCenter
        Accessible.name: root.accessibleName

        // Anything typed that is not a number gives the value back.
        onEditingFinished: {
            const typed = parseInt(box.text);
            root.set(isNaN(typed) ? root.value : typed);
        }
        Keys.onUpPressed: root.set(root.value + 1)
        Keys.onDownPressed: root.set(root.value - 1)

        // As the text box's: the bottom rows of the rounded box, 1 px strong at rest and 2 px of
        // accent with the focus.
        background: Rectangle {
            radius: 4
            color: box.activeFocus ? Colors.controlFillInputActive : box.hovered ? Colors.controlFillHover : Colors.controlFill
            border.width: 1
            border.color: Colors.controlStroke

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

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        SpinButton {
            glyph: "" // ChevronUp
            enabled: root.value < root.to
            Accessible.name: Texts.increase
            onClicked: root.set(root.value + 1)
        }
        SpinButton {
            glyph: "" // ChevronDown
            enabled: root.value > root.from
            Accessible.name: Texts.decrease
            onClicked: root.set(root.value - 1)
        }
    }

    component SpinButton: T.AbstractButton {
        id: spin

        property string glyph

        implicitWidth: 32
        implicitHeight: 24
        hoverEnabled: true
        focusPolicy: Qt.NoFocus
        autoRepeat: true

        background: Rectangle {
            radius: 4
            color: spin.down ? Colors.subtleFillPressed : spin.hovered ? Colors.subtleFillHover : "transparent"
        }
        contentItem: Text {
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: spin.glyph
            color: !spin.enabled ? Colors.textDisabled : spin.down ? Colors.textSecondary : Colors.textPrimary
            font.family: Typography.iconFont
            font.pixelSize: Typography.chevron
        }
    }
}
