// The tray icon (#12, ADR-0010): a click opens the tray list, a right click its menu. On
// Windows, Qt draws the menu with Windows' own, since the app is a QGuiApplication.
import QtQuick
import Qt.labs.platform as Platform
import Jiffin

Platform.SystemTrayIcon {
    id: icon

    required property Tray tray

    visible: true
    icon.source: tray.icon
    tooltip: Texts.appName
    menu: Platform.Menu {
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
