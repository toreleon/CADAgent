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
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property color borderSoft: theme.borderSoft
    readonly property color codeBg: theme.codeBg
    readonly property color errColor: theme.errColor
    readonly property color okColor: theme.okColor
    readonly property string monoFamily: theme.monoFamily

    readonly property var meta: rowModel ? rowModel.meta : ({})
    readonly property string ev: meta && meta.event ? meta.event : ""
    readonly property string msg: meta && meta.message ? meta.message : ""
    readonly property string decision: meta && meta.decision ? meta.decision : ""
    readonly property bool blocked: decision === "block"

    implicitHeight: chip.implicitHeight + rowPadY * 2

    Rectangle {
        id: chip
        x: gutter
        y: rowPadY
        width: parent.width - gutter - 12
        radius: radiusSm
        color: codeBg
        border.color: blocked ? errColor : borderSoft
        border.width: 1
        implicitHeight: line.implicitHeight + 8

        RowLayout {
            id: line
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            spacing: 6

            Text {
                text: blocked ? "⛔" : "⚙"
                color: blocked ? errColor : okColor
                font.pixelSize: fontSm
            }
            Text {
                text: ev
                color: fgDim
                font.family: monoFamily
                font.pixelSize: fontSm
            }
            Text {
                text: blocked ? qsTr("blocked") : qsTr("hook")
                color: blocked ? errColor : fgDim
                font.pixelSize: fontSm
                font.italic: true
            }
            Text {
                Layout.fillWidth: true
                text: msg
                color: fg
                wrapMode: Text.Wrap
                font.pixelSize: fontSm
                visible: msg.length > 0
            }
        }
    }
}
