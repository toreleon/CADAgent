// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

RowLayout {
    id: topbar

    property var bridge
    property var theme
    property alias historyButton: historyBtn
    signal openHistory()

    readonly property color accent: theme.accent
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property string monoFamily: theme.monoFamily

    spacing: 6

    Text {
        text: !bridge || bridge.currentAgent === "main" ? "" : "[" + bridge.currentAgent + "]"
        visible: text.length > 0
        color: accent
        font.pixelSize: 10
        font.family: monoFamily
    }

    Text {
        text: bridge ? bridge.milestoneSummary : ""
        visible: text.length > 0
        color: fgDim
        font.pixelSize: 10
        font.family: monoFamily
        elide: Text.ElideRight
        Layout.maximumWidth: 240
    }

    Item { Layout.fillWidth: true }

    component TopbarGlyph: ToolButton {
        property string symbol: ""
        property string tip: ""
        implicitWidth: 24
        implicitHeight: 24
        ToolTip.visible: hovered
        ToolTip.text: tip
        background: Rectangle { color: "transparent" }
        contentItem: Text {
            text: symbol
            color: parent.hovered ? topbar.fg : topbar.fgDim
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    TopbarGlyph {
        symbol: "＋"; tip: qsTr("New chat")
        onClicked: bridge.newChat()
    }
    TopbarGlyph {
        id: historyBtn
        symbol: "⟳"; tip: qsTr("History")
        onClicked: topbar.openHistory()
    }
    TopbarGlyph {
        symbol: "⚙"; tip: qsTr("Configure LLM")
        onClicked: bridge.configureLlm()
    }
}
