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
    readonly property string monoFamily: theme.monoFamily

    implicitHeight: col.implicitHeight + rowPadY * 2 + 6

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        color: Qt.rgba(accent.r, accent.g, accent.b, 0.06)
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
        spacing: 6

        Text {
            text: "◆ " + qsTr("Plan — ready for approval")
            color: accent
            font.pixelSize: fontMd
            font.bold: true
        }

        Text {
            text: rowModel && rowModel.meta ? (rowModel.meta.path || "") : ""
            color: fgMuted
            font.pixelSize: fontSm
            font.family: monoFamily
            visible: text.length > 0
        }

        Rectangle {
            width: col.width
            implicitHeight: bodyText.implicitHeight + 12
            color: codeBg
            radius: radiusSm
            Text {
                id: bodyText
                x: 8; y: 6
                width: parent.width - 16
                text: rowModel ? rowModel.text : ""
                wrapMode: Text.Wrap
                color: fgDim
                font.pixelSize: fontSm
                font.family: monoFamily
                textFormat: Text.PlainText
            }
        }

        Text {
            visible: rowModel && rowModel.meta && !rowModel.meta.approved
            text: qsTr("⎿  the agent called exit_plan_mode — execution is unlocked for the next turn")
            color: fgMuted
            font.italic: true
            font.pixelSize: fontSm
        }
    }
}
