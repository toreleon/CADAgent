// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Item {
    id: chip

    property var bridge
    property var theme
    property Item panelItem
    property real panelWidth: 360
    property string activeLabel: qsTr("Untitled")

    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property color fgMuted: theme.fgMuted
    readonly property color borderColor: theme.border
    readonly property color borderSoft: theme.borderSoft
    readonly property int radiusSm: theme.radiusSm
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property string monoFamily: theme.monoFamily

    function _stripExt(name) {
        if (!name) return ""
        var s = String(name)
        var lower = s.toLowerCase()
        if (lower.endsWith(".fcstd")) return s.slice(0, -6)
        return s
    }

    function _basenameNoExt(path) {
        if (!path) return ""
        var s = String(path)
        var i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"))
        var base = i >= 0 ? s.slice(i + 1) : s
        return _stripExt(base)
    }

    function _refreshLabel() {
        var raw
        try {
            raw = bridge ? bridge.openDocsList() : "[]"
        } catch (e) {
            raw = "[]"
        }
        var entries = []
        try { entries = JSON.parse(raw || "[]") } catch (e) { entries = [] }
        for (var i = 0; i < entries.length; ++i) {
            if (entries[i].active) {
                var path = entries[i].path || ""
                var label = path ? _basenameNoExt(path)
                                 : _stripExt(entries[i].label || entries[i].name || "")
                activeLabel = label || qsTr("Untitled")
                return
            }
        }
        activeLabel = qsTr("Untitled")
    }

    implicitWidth: chipBg.implicitWidth
    implicitHeight: 22

    Connections {
        target: bridge
        ignoreUnknownSignals: true
        function onActiveDocChanged(_path) { chip._refreshLabel() }
    }

    Component.onCompleted: _refreshLabel()

    Rectangle {
        id: chipBg
        anchors.fill: parent
        radius: radiusSm
        color: chipMouse.containsMouse
               ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
               : "transparent"
        border.color: borderSoft
        border.width: 1
        implicitWidth: chipRow.implicitWidth + 12

        RowLayout {
            id: chipRow
            anchors.fill: parent
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            spacing: 4

            Text {
                text: "▣"
                color: fgDim
                font.pixelSize: fontSm
            }
            Text {
                text: chip.activeLabel
                color: fg
                font.pixelSize: fontSm
                font.family: monoFamily
                elide: Text.ElideRight
                Layout.maximumWidth: 160
            }
            Text {
                text: "▾"
                color: fgMuted
                font.pixelSize: 9
            }
        }

        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                docsPopup.refresh()
                docsPopup.open()
            }
        }
    }

    Popup {
        id: docsPopup

        property var entries: []

        function refresh() {
            try {
                entries = JSON.parse(bridge ? bridge.openDocsList() || "[]" : "[]")
            } catch (e) {
                entries = []
            }
            chip._refreshLabel()
        }

        x: {
            if (!chip || !panelItem) return 0
            var p = chip.mapToItem(panelItem, 0, 0)
            return Math.max(6, p.x)
        }
        y: {
            if (!chip || !panelItem) return 24
            var p = chip.mapToItem(panelItem, 0, 0)
            return p.y + chip.height + 4
        }
        width: Math.min(320, panelWidth - 12)
        height: Math.min(360, docsColumn.implicitHeight + 12)
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: theme.pal.window
            border.color: borderColor
            border.width: 1
            radius: theme.radiusMd
        }

        contentItem: ColumnLayout {
            id: docsColumn
            anchors.fill: parent
            spacing: 0

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 4
                text: qsTr("Open documents")
                color: fg
                font.pixelSize: fontMd
                font.bold: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: borderSoft
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.bottomMargin: 12
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("No documents open.")
                color: fgMuted
                font.pixelSize: fontSm
                visible: docsPopup.entries.length === 0
            }

            ListView {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(220, contentHeight)
                clip: true
                visible: docsPopup.entries.length > 0
                model: docsPopup.entries
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: 36
                    color: docMouse.containsMouse
                           ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                           : "transparent"

                    MouseArea {
                        id: docMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (bridge) bridge.setActiveDocument(modelData.name || modelData.label || "")
                            chip._refreshLabel()
                            docsPopup.close()
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        Text {
                            text: modelData.active ? "●" : "○"
                            color: modelData.active ? theme.accent : fgMuted
                            font.pixelSize: fontMd
                            Layout.preferredWidth: 12
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                text: chip._stripExt(modelData.label || modelData.name || qsTr("Untitled"))
                                color: fg
                                font.pixelSize: fontMd
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Text {
                                text: modelData.path || qsTr("(unsaved)")
                                color: fgMuted
                                font.pixelSize: 10
                                font.family: monoFamily
                                elide: Text.ElideLeft
                                Layout.fillWidth: true
                                visible: text.length > 0
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: borderSoft
            }

            // Open… / New row. Both run the matching slash-style request through
            // the agent's tools by submitting a directive prompt; this avoids
            // wiring a second filesystem dialog into Python while still feeling
            // immediate to the user.
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Layout.bottomMargin: 6
                Layout.leftMargin: 6
                Layout.rightMargin: 6
                spacing: 4

                ToolButton {
                    Layout.fillWidth: true
                    text: qsTr("＋ New")
                    background: Rectangle {
                        color: parent.hovered
                               ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                               : "transparent"
                        radius: radiusSm
                    }
                    contentItem: Text {
                        text: parent.text
                        color: fg
                        font.pixelSize: fontSm
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (bridge) bridge.submit(qsTr("Create a new empty FreeCAD document and make it active."))
                        docsPopup.close()
                    }
                }
                ToolButton {
                    Layout.fillWidth: true
                    text: qsTr("⌕ Open…")
                    background: Rectangle {
                        color: parent.hovered
                               ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                               : "transparent"
                        radius: radiusSm
                    }
                    contentItem: Text {
                        text: parent.text
                        color: fg
                        font.pixelSize: fontSm
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (bridge) bridge.submit(qsTr("Open an existing FreeCAD document and make it active."))
                        docsPopup.close()
                    }
                }
            }
        }
    }
}
