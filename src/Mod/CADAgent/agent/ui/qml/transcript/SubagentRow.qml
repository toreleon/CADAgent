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

            property string _action: rowModel && rowModel.meta ? (rowModel.meta.action || "start") : "start"
            property string _agent: rowModel && rowModel.meta ? (rowModel.meta.agent  || "")    : ""
            implicitHeight: 18
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Text {
                    text: _action === "start" ? "┌" : "└"
                    color: fgMuted
                    font.family: monoFamily
                    font.pixelSize: fontSm
                }
                Text {
                    text: _action === "start"
                        ? (qsTr("→ delegate") + "  [" + _agent + "]"
                           + (rowModel && rowModel.text ? "  " + rowModel.text : ""))
                        : (qsTr("← return") + "  [" + _agent + "]")
                    color: fgDim
                    font.pixelSize: fontSm
                    font.italic: true
                    font.family: monoFamily
                }
            }
        }
