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

            implicitHeight: permCol.implicitHeight + rowPadY * 2 + 4

            Text {
                x: 6
                y: rowPadY + 2
                text: "⏺"
                color: rowModel && rowModel.meta && rowModel.meta.pending ? accent : fgMuted
                font.pixelSize: fontMd
            }

            Column {
                id: permCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 4

                Text {
                    width: parent.width
                    text: {
                        var n = rowModel ? rowModel.text : ""
                        var inp = rowModel && rowModel.meta && rowModel.meta.inputPreview
                                  ? rowModel.meta.inputPreview : ""
                        if (inp.length === 0) return n + "()"
                        return inp.indexOf("\n") < 0
                            ? n + "(" + inp + ")"
                            : n + "(…)"
                    }
                    color: fg
                    wrapMode: Text.Wrap
                    font.pixelSize: fontMd
                    font.family: monoFamily
                }

                // Multi-line input (tree corner)
                Row {
                    visible: rowModel && rowModel.meta && rowModel.meta.inputPreview
                             && rowModel.meta.inputPreview.indexOf("\n") >= 0
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        width: permCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.inputPreview) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // Action row — inline plain-text buttons, no frames.
                Row {
                    visible: rowModel && rowModel.meta && rowModel.meta.pending
                    spacing: 12
                    topPadding: 2

                    Text {
                        text: qsTr("⎿  approve?")
                        color: fgDim
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }

                    MouseArea {
                        width: approveLabel.width
                        height: approveLabel.height
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.decidePermission(rowModel.meta.reqId, true, "")
                        Text {
                            id: approveLabel
                            text: "[" + qsTr("yes") + "]"
                            color: parent.containsMouse ? okColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                            font.bold: true
                        }
                        hoverEnabled: true
                    }

                    MouseArea {
                        width: rejectLabel.width
                        height: rejectLabel.height
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.decidePermission(rowModel.meta.reqId, false, "")
                        Text {
                            id: rejectLabel
                            text: "[" + qsTr("no") + "]"
                            color: parent.containsMouse ? errColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        hoverEnabled: true
                    }
                }

                // Resolved state — shows the decision, greyed.
                Row {
                    visible: rowModel && rowModel.meta && !rowModel.meta.pending
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        text: (rowModel && rowModel.meta && rowModel.meta.decision) || ""
                        color: fgMuted
                        font.italic: true
                        font.pixelSize: fontSm
                    }
                }
            }
        }
