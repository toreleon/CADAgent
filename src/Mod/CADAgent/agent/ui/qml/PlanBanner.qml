// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: planBanner

    property var bridge
    property var theme

    readonly property int radiusSm: theme.radiusSm
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property color accent: theme.accent
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim

    visible: bridge && bridge.permissionMode === "plan"
    height: visible ? 24 : 0
    color: Qt.rgba(accent.r, accent.g, accent.b, 0.08)
    border.color: Qt.rgba(accent.r, accent.g, accent.b, 0.35)
    border.width: 1
    radius: radiusSm

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 6
        spacing: 8

        Text {
            text: "◆"
            color: accent
            font.pixelSize: fontMd
        }
        Text {
            Layout.fillWidth: true
            text: qsTr("Plan mode — read-only exploration; I'll present a plan before editing.")
            color: fg
            font.pixelSize: fontSm
            elide: Text.ElideRight
        }
        ToolButton {
            id: planBannerClose
            implicitWidth: 18
            implicitHeight: 18
            ToolTip.visible: hovered
            ToolTip.text: qsTr("Exit plan mode")
            onClicked: bridge.setPermissionMode("default")
            background: Rectangle { color: "transparent" }
            contentItem: Text {
                text: "✕"
                color: planBannerClose.hovered ? fg : fgDim
                font.pixelSize: fontSm
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
