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

    property bool expanded: false

    implicitHeight: col.implicitHeight + rowPadY * 2 + 6

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        color: Qt.rgba(accent.r, accent.g, accent.b, 0.04)
        border.color: borderSoft
        border.width: 1
        radius: radiusSm
    }

    Column {
        id: col
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: gutter
        anchors.rightMargin: 12
        y: rowPadY + 2
        spacing: 4

        Text {
            text: "✎ " + (rowModel && rowModel.meta && rowModel.meta.summary
                          ? rowModel.meta.summary
                          : qsTr("Pending edit"))
            color: fg
            font.pixelSize: fontMd
            wrapMode: Text.Wrap
            width: col.width
        }

        MouseArea {
            width: toggleText.width
            height: toggleText.height
            cursorShape: Qt.PointingHandCursor
            onClicked: expanded = !expanded
            Text {
                id: toggleText
                text: expanded ? qsTr("⎿  hide script") : qsTr("⎿  view script")
                color: fgMuted
                font.pixelSize: fontSm
                font.family: monoFamily
            }
        }

        Rectangle {
            visible: expanded
            width: col.width
            implicitHeight: scriptText.implicitHeight + 12
            color: codeBg
            radius: radiusSm
            Text {
                id: scriptText
                x: 8; y: 6
                width: parent.width - 16
                text: rowModel && rowModel.meta ? (rowModel.meta.script || "") : ""
                wrapMode: Text.Wrap
                color: fgDim
                font.pixelSize: fontSm
                font.family: monoFamily
                textFormat: Text.PlainText
            }
        }

        Row {
            visible: rowModel && rowModel.meta && rowModel.meta.pending
            spacing: 12
            topPadding: 2

            Text {
                text: qsTr("⎿  apply?")
                color: fgDim
                font.pixelSize: fontSm
                font.family: monoFamily
            }

            MouseArea {
                id: approveArea
                width: approveLabel.width
                height: approveLabel.height
                cursorShape: Qt.PointingHandCursor
                hoverEnabled: true
                onClicked: bridge.decideEditApproval(rowModel.meta.reqId, true)
                Text {
                    id: approveLabel
                    text: "[" + qsTr("apply") + "]"
                    color: approveArea.containsMouse ? okColor : fgDim
                    font.pixelSize: fontSm
                    font.family: monoFamily
                    font.bold: true
                }
            }

            MouseArea {
                id: rejectArea
                width: rejectLabel.width
                height: rejectLabel.height
                cursorShape: Qt.PointingHandCursor
                hoverEnabled: true
                onClicked: bridge.decideEditApproval(rowModel.meta.reqId, false)
                Text {
                    id: rejectLabel
                    text: "[" + qsTr("reject") + "]"
                    color: rejectArea.containsMouse ? errColor : fgDim
                    font.pixelSize: fontSm
                    font.family: monoFamily
                }
            }
        }

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
