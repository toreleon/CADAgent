// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

        Item {
            // rowModel is forwarded from the delegate Loader via runtime parent
            // chain. Having it as a root property lets nested children bind to
            // `rowModel.*` through normal QML scope lookup.
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

            implicitHeight: userText.implicitHeight + rowPadY * 2 + 4
            Text {
                id: userMark
                x: 6
                y: rowPadY + 2
                text: ">"
                color: fgDim
                font.family: monoFamily
                font.pixelSize: fontMd
            }
            Text {
                id: userText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                text: rowModel ? rowModel.text : ""
                color: fg
                wrapMode: Text.Wrap
                font.pixelSize: fontMd
                textFormat: Text.PlainText
            }
        }
