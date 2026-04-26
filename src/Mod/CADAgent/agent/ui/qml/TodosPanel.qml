// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Item {
    id: panel

    property var bridge
    property var theme

    property bool collapsed: false
    readonly property var todos: bridge ? (bridge.currentTodos || []) : []

    readonly property int radiusSm: theme ? theme.radiusSm : 3
    readonly property int fontSm: theme ? theme.fontSm : 11
    readonly property int fontMd: theme ? theme.fontMd : 12
    readonly property color accent: theme ? theme.accent : "#5b9dd9"
    readonly property color fg: theme ? theme.fg : "#222"
    readonly property color fgDim: theme ? theme.fgDim : "#888"
    readonly property color fgMuted: theme ? theme.fgMuted : "#aaa"
    readonly property color borderSoft: theme ? theme.borderSoft : "#333"
    readonly property color okColor: theme ? theme.okColor : "#5ec270"
    readonly property string monoFamily: theme ? theme.monoFamily : "Menlo"

    visible: todos.length > 0
    implicitHeight: visible ? frame.implicitHeight + 4 : 0

    Rectangle {
        id: frame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.topMargin: 2
        color: theme ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.04)
                     : "transparent"
        border.color: borderSoft
        border.width: 1
        radius: radiusSm
        implicitHeight: contentCol.implicitHeight + 12

        ColumnLayout {
            id: contentCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 6
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    text: panel.collapsed ? "▸" : "▾"
                    color: fgDim
                    font.pixelSize: fontSm
                    font.family: monoFamily
                    Layout.preferredWidth: 12
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    text: qsTr("Todos")
                    color: fgMuted
                    font.pixelSize: 10
                    font.family: monoFamily
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: {
                        var done = 0
                        for (var i = 0; i < panel.todos.length; ++i)
                            if (panel.todos[i].status === "completed") done++
                        return done + "/" + panel.todos.length
                    }
                    color: fgDim
                    font.pixelSize: 10
                    font.family: monoFamily
                }
            }

            Column {
                id: listCol
                Layout.fillWidth: true
                visible: !panel.collapsed
                spacing: 3

                Repeater {
                    model: panel.todos
                    delegate: Row {
                        required property var modelData
                        spacing: 6
                        readonly property string _status: modelData.status || "pending"

                        Text {
                            text: _status === "completed" ? "☒"
                                : _status === "in_progress" ? "◐"
                                : "☐"
                            color: _status === "completed" ? okColor
                                 : _status === "in_progress" ? accent
                                 : fgDim
                            font.pixelSize: fontMd
                            font.family: monoFamily
                            width: 16
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            text: _status === "in_progress" && modelData.activeForm
                                  ? modelData.activeForm
                                  : (modelData.content || "")
                            color: _status === "completed" ? fgMuted : fg
                            font.pixelSize: fontMd
                            font.strikeout: _status === "completed"
                            font.bold: _status === "in_progress"
                            wrapMode: Text.Wrap
                            width: listCol.width - 22
                        }
                    }
                }
            }
        }

        MouseArea {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 24
            cursorShape: Qt.PointingHandCursor
            onClicked: panel.collapsed = !panel.collapsed
        }
    }
}
