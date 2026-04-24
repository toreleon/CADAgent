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

            implicitHeight: thinkText.implicitHeight + rowPadY * 2
            Text {
                x: 6
                y: rowPadY
                text: "✻"
                color: fgDim
                font.pixelSize: fontMd
            }
            Text {
                id: thinkText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY
                text: rowModel ? rowModel.text : ""
                color: fgDim
                wrapMode: Text.Wrap
                font.italic: true
                font.pixelSize: fontSm
            }
        }
