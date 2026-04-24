// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

        Item {
            property var rowModel: parent ? parent.rowModel : null
    property var bridge: parent ? parent.bridge : null
    property var theme: parent ? parent.theme : null

    readonly property int gutter: theme.gutter
    readonly property int rowPadY: theme.rowPadY
    readonly property int radiusSm: theme.radiusSm
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property color accent: theme.accent
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property color fgMuted: theme.fgMuted
    readonly property color borderSoft: theme.borderSoft
    readonly property color codeBg: theme.codeBg
    readonly property color okColor: theme.okColor
    readonly property color errColor: theme.errColor
    readonly property string monoFamily: theme.monoFamily

            property var _todos: (rowModel && rowModel.meta && rowModel.meta.todos)
                                 ? rowModel.meta.todos : []
            implicitHeight: todosCol.implicitHeight + 10

            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 6
                anchors.rightMargin: 6
                anchors.topMargin: 2
                anchors.bottomMargin: 2
                color: Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.04)
                border.color: borderSoft
                border.width: 1
                radius: radiusSm
            }

            Column {
                id: todosCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                y: 6
                spacing: 3

                Text {
                    text: qsTr("Todos")
                    color: fgMuted
                    font.pixelSize: 10
                    font.family: monoFamily
                    font.bold: true
                }

                Repeater {
                    model: _todos
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
                            width: todosCol.width - 22
                        }
                    }
                }
            }
        }
