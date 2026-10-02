// A Fluent 2 progress bar, drawn by us (ADR-0010): a 1 px track and a 3 px bar in the accent, as
// WinUI's ProgressBar_themeresources.xaml (microsoft-ui-xaml at 8463f45162). Paused, the bar
// takes the caution colour; in error, the critical one.
import QtQuick
import QtQuick.Templates as T

T.ProgressBar {
    id: control

    property bool paused: false
    property bool error: false

    implicitWidth: 200
    implicitHeight: 3

    background: Item {
        Rectangle {
            y: 1
            width: parent.width
            height: 1
            radius: 0.5
            color: Colors.controlStrongStroke
        }
    }

    contentItem: Item {
        Rectangle {
            width: control.visualPosition * parent.width
            height: 3
            radius: 1.5
            color: control.error ? Colors.critical : control.paused ? Colors.caution : Colors.accent
        }
    }
}
