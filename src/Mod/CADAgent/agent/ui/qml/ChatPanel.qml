// SPDX-License-Identifier: LGPL-2.1-or-later
// CAD Agent chat panel (QML) — Claude Code CLI aesthetic.
//
// The Python side (qml_panel.py) exposes two context properties:
//   - bridge:   QmlChatBridge  — slots for send/stop/new/configure/decide
//   - messages: MessagesModel  — QAbstractListModel of chat rows
// Row roles: kind, text, meta.

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: sysPal.window

    SystemPalette { id: sysPal; colorGroup: SystemPalette.Active }

    readonly property alias pal: sysPal
    readonly property int gutter: 22
    readonly property int rowPadY: 3
    readonly property int radiusSm: 3
    readonly property int radiusMd: 4
    readonly property int fontSm: 11
    readonly property int fontMd: 12
    readonly property color accent: sysPal.highlight
    readonly property color accentFg: sysPal.highlightedText
    readonly property color fg: sysPal.text
    readonly property color fgDim: Qt.rgba(sysPal.text.r, sysPal.text.g, sysPal.text.b, 0.55)
    readonly property color fgMuted: Qt.rgba(sysPal.text.r, sysPal.text.g, sysPal.text.b, 0.40)
    readonly property color border: Qt.rgba(sysPal.text.r, sysPal.text.g, sysPal.text.b, 0.18)
    readonly property color borderSoft: Qt.rgba(sysPal.text.r, sysPal.text.g, sysPal.text.b, 0.10)
    readonly property color codeBg: Qt.rgba(0.5, 0.5, 0.5, 0.12)
    readonly property color okColor: "#5ec270"
    readonly property color errColor: "#e05757"
    readonly property string monoFamily: "Menlo"
    readonly property var chatBridge: bridge
    readonly property var messageModel: messages

    readonly property var modeDefs: [
        { mode: "default",            icon: "●", title: qsTr("Ask before edits"),
          desc: qsTr("Claude will ask for approval before making each edit") },
        { mode: "acceptEdits",        icon: "✎", title: qsTr("Edit automatically"),
          desc: qsTr("Claude will edit your selected text or the whole file") },
        { mode: "plan",               icon: "◆", title: qsTr("Plan mode"),
          desc: qsTr("Claude will explore the code and present a plan before editing") },
        { mode: "bypassPermissions",  icon: "⛨", title: qsTr("Bypass permissions"),
          desc: qsTr("Claude will not ask for approval before running potentially dangerous commands") }
    ]

    function modeTitle(m) {
        for (var i = 0; i < modeDefs.length; ++i)
            if (modeDefs[i].mode === m) return modeDefs[i].title
        return qsTr("Ask before edits")
    }
    function modeIcon(m) {
        for (var i = 0; i < modeDefs.length; ++i)
            if (modeDefs[i].mode === m) return modeDefs[i].icon
        return "●"
    }
    function modeColor(m) {
        return m === "bypassPermissions" ? errColor
             : m === "plan"              ? accent
             : fgDim
    }
    function cycleMode() {
        var cur = chatBridge ? chatBridge.permissionMode : "default"
        var idx = 0
        for (var i = 0; i < modeDefs.length; ++i)
            if (modeDefs[i].mode === cur) { idx = i; break }
        chatBridge.setPermissionMode(modeDefs[(idx + 1) % modeDefs.length].mode)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ChatTopBar {
            id: topbar
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.topMargin: 4
            bridge: root.chatBridge
            theme: root
            panelItem: root
            panelWidth: root.width
            onOpenHistory: {
                historyPopup.refresh()
                historyPopup.open()
            }
        }

        PlanBanner {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.topMargin: 4
            bridge: root.chatBridge
            theme: root
        }

        TodosPanel {
            Layout.fillWidth: true
            Layout.topMargin: 2
            bridge: root.chatBridge
            theme: root
        }

        TranscriptView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 0
            Layout.rightMargin: 0
            Layout.topMargin: 2
            bridge: root.chatBridge
            messages: root.messageModel
            theme: root
        }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: (root.chatBridge && root.chatBridge.busy) ? 16 : 0
            visible: root.chatBridge && root.chatBridge.busy
            Text {
                anchors.left: parent.left
                anchors.leftMargin: gutter
                anchors.verticalCenter: parent.verticalCenter
                text: "✻ " + qsTr("working…")
                color: fgDim
                font.pixelSize: fontSm
                font.italic: true
            }
        }

        ChatComposer {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.bottomMargin: 6
            Layout.topMargin: 2
            bridge: root.chatBridge
            theme: root
            onSubmitted: function (text) { root.chatBridge.submit(text) }
        }
    }

    HistoryPopup {
        id: historyPopup
        bridge: root.chatBridge
        theme: root
        anchorItem: topbar.historyButton
        panelItem: root
        panelWidth: root.width
    }
}
