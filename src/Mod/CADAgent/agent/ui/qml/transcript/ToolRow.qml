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

            implicitHeight: toolCol.implicitHeight + rowPadY * 2 + 4

            Text {
                x: 6
                y: rowPadY + 2
                text: "⏺"
                color: rowModel && rowModel.meta && rowModel.meta.isError ? errColor
                       : (rowModel && rowModel.meta && rowModel.meta.status === "OK" ? okColor : accent)
                font.pixelSize: fontMd
            }

            Column {
                id: toolCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 2

                // Header line: "[agent] name(input)". Clickable when the
                // row has verification children — toggles collapse.
                MouseArea {
                    width: toolHeader.implicitWidth
                    height: toolHeader.implicitHeight
                    cursorShape: (rowModel && rowModel.meta
                                  && rowModel.meta.children
                                  && rowModel.meta.children.length > 0)
                                 ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        if (rowModel && rowModel.meta
                            && rowModel.meta.children
                            && rowModel.meta.children.length > 0)
                            bridge.toggleCollapse(rowModel.rowId)
                    }
                    Text {
                        id: toolHeader
                        width: toolCol.width
                        text: {
                            var n = rowModel ? rowModel.text : ""
                            var a = rowModel && rowModel.meta && rowModel.meta.agent
                                    ? "[" + rowModel.meta.agent + "] " : ""
                            var inp = rowModel && rowModel.meta && rowModel.meta.inputPreview
                                      ? rowModel.meta.inputPreview : ""
                            var body = (inp.length === 0) ? (n + "()")
                                     : (inp.indexOf("\n") < 0 ? n + "(" + inp + ")" : n + "(…)")
                            return a + body
                        }
                        color: fg
                        wrapMode: Text.Wrap
                        font.pixelSize: fontMd
                        font.family: monoFamily
                    }
                }

                // Multi-line input (indented, tree corner)
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
                        width: toolCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.inputPreview) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // Result (tree corner + preview)
                Row {
                    visible: !!(rowModel && rowModel.meta && rowModel.meta.resultPreview)
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        width: toolCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.resultPreview) || ""
                        color: rowModel && rowModel.meta && rowModel.meta.isError ? errColor : fg
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // "running…" placeholder until a result arrives.
                Row {
                    visible: rowModel && rowModel.meta
                             && !rowModel.meta.resultPreview
                             && rowModel.meta.status === "…"
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        text: qsTr("running…")
                        color: fgMuted
                        font.italic: true
                        font.pixelSize: fontSm
                    }
                }
            }
        }
