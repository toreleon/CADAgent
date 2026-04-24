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

            property string _agent: rowModel && rowModel.meta ? (rowModel.meta.agent || "") : ""
            property bool _partial: rowModel && rowModel.meta ? (rowModel.meta.isPartial === true) : false
            implicitHeight: asstText.implicitHeight + rowPadY * 2 + 4
            Text {
                x: 6
                y: rowPadY + 2
                text: _partial ? "✻" : "⏺"
                color: accent
                font.pixelSize: fontMd
            }
            Text {
                id: agentChip
                visible: _agent.length > 0
                x: gutter
                y: rowPadY + 2
                text: "[" + _agent + "]"
                color: fgDim
                font.pixelSize: fontSm
                font.family: monoFamily
            }
            Text {
                id: asstText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: _agent.length > 0 ? gutter + agentChip.implicitWidth + 6 : gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                text: (rowModel ? rowModel.text : "") + (_partial ? " …" : "")
                color: fg
                wrapMode: Text.Wrap
                textFormat: Text.MarkdownText
                font.pixelSize: fontMd
                onLinkActivated: Qt.openUrlExternally(link)
            }
        }
