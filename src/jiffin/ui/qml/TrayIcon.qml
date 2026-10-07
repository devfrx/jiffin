// The tray icon (#12, ADR-0010): a click opens the tray list, a right click its menu, with the
// pause (ADR-0024), Settings and Quit. On Windows, Qt draws the menu with Windows' own, since
// the app is a QGuiApplication.
import QtQuick
import Qt.labs.platform as Platform
import Jiffin

Platform.SystemTrayIcon {
    id: icon

    required property Tray tray

    visible: true
    icon.source: tray.icon
    tooltip: tray.paused ? Texts.appName + "\n" + Texts.paused : Texts.appName
    menu: Platform.Menu {
        Platform.MenuItem {
            text: Texts.pauseHour
            visible: !icon.tray.paused
            onTriggered: icon.tray.pauseHour()
        }
        Platform.MenuItem {
            text: Texts.pauseTomorrow
            visible: !icon.tray.paused
            onTriggered: icon.tray.pauseTomorrow()
        }
        Platform.MenuItem {
            text: Texts.resume
            visible: icon.tray.paused
            onTriggered: icon.tray.resume()
        }
        Platform.MenuSeparator {}
        Platform.MenuItem {
            text: Texts.settings
            onTriggered: icon.tray.settings()
        }
        Platform.MenuItem {
            text: Texts.quit
            onTriggered: icon.tray.quit()
        }
    }

    onActivated: reason => {
        if (reason === Platform.SystemTrayIcon.Trigger)
            icon.tray.click();
    }
}
