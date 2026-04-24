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

            property bool _collapsed: rowModel && rowModel.meta ? (rowModel.meta.collapsed !== false) : true
            implicitHeight: dCol.implicitHeight + rowPadY * 2 + 4
            Text {
                x: 6
                y: rowPadY + 2
                text: "★"
                color: accent
                font.pixelSize: fontMd
            }
            Column {
                id: dCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 3

                MouseArea {
                    width: dHeader.width
                    height: dHeader.height
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (rowModel) bridge.toggleCollapse(rowModel.rowId)
                    Row {
                        id: dHeader
                        spacing: 6
                        Text {
                            text: _collapsed ? "▸" : "▾"
                            color: fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        Text {
                            text: rowModel ? rowModel.text : ""
                            color: fg
                            font.pixelSize: fontMd
                            font.bold: true
                        }
                    }
                }

                Column {
                    visible: !_collapsed
                    width: dCol.width
                    spacing: 2

                    Text {
                        width: parent.width
                        visible: rowModel && rowModel.meta && rowModel.meta.rationale
                                 && rowModel.meta.rationale.length > 0
                        text: (rowModel && rowModel.meta && rowModel.meta.rationale) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                    }

                    Repeater {
                        model: (rowModel && rowModel.meta && rowModel.meta.alternatives) || []
                        delegate: Row {
                            width: dCol.width
                            spacing: 6
                            Text {
                                text: "·"
                                color: fgMuted
                                font.pixelSize: fontSm
                                width: 8
                            }
                            Text {
                                width: dCol.width - 14
                                text: modelData.label
                                      ? (modelData.label + (modelData.reason ? "  — " + modelData.reason : ""))
                                      : (typeof modelData === "string" ? modelData : "")
                                color: fgDim
                                wrapMode: Text.Wrap
                                font.pixelSize: fontSm
                            }
                        }
                    }

                    Row {
                        visible: (rowModel && rowModel.meta && rowModel.meta.tags
                                  && rowModel.meta.tags.length > 0) || false
                        spacing: 4
                        topPadding: 2
                        Repeater {
                            model: (rowModel && rowModel.meta && rowModel.meta.tags) || []
                            delegate: Rectangle {
                                color: codeBg
                                radius: radiusSm
                                implicitHeight: tagText.implicitHeight + 2
                                implicitWidth: tagText.implicitWidth + 8
                                Text {
                                    id: tagText
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: fgDim
                                    font.pixelSize: 10
                                    font.family: monoFamily
                                }
                            }
                        }
                    }
                }
            }
        }
