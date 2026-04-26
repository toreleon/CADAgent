// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

RowLayout {
    id: topbar

    property var bridge
    property var theme
    property Item panelItem
    property real panelWidth: 360
    property alias historyButton: historyBtn
    signal openHistory()

    readonly property color accent: theme.accent
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property string monoFamily: theme.monoFamily

    spacing: 6

    WorkspaceChip {
        bridge: topbar.bridge
        theme: topbar.theme
        panelItem: topbar.panelItem
        panelWidth: topbar.panelWidth
    }

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

    Text {
        id: contextLabel
        readonly property real pct: bridge ? bridge.contextUsedPct : 0.0
        visible: bridge && (bridge.contextCompacting || pct > 0.5)
        text: bridge && bridge.contextCompacting
            ? qsTr("Compacting…")
            : qsTr("%1% until auto-compact").arg(
                Math.max(0, Math.round((1.0 - pct) * 100)))
        font.italic: bridge && bridge.contextCompacting
        color: fgDim
        font.pixelSize: 10
        font.family: monoFamily
        Layout.maximumWidth: 180
        elide: Text.ElideRight
    }

    Rectangle {
        id: contextStrip
        readonly property real pct: bridge ? bridge.contextUsedPct : 0.0
        height: 3
        width: parent ? parent.width * pct : 0
        anchors.bottom: parent ? parent.bottom : undefined
        anchors.left: parent ? parent.left : undefined
        z: 5
        color: pct >= 0.95
            ? "#d44a3a"
            : (pct >= 0.80 ? "#d49b1c" : (theme ? theme.accent : "#3a8fd4"))
        visible: pct > 0.0

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true
            ToolTip.visible: containsMouse
            ToolTip.text: qsTr("Compact context now")
            onClicked: { if (bridge) bridge.compactNow() }
        }
    }

    ToolButton {
        id: hooksIndicator
        property string source: "none"
        property string settingsText: "{}"

        function refresh() {
            if (!bridge || !bridge.activeHooksSettings) return
            try {
                var parsed = JSON.parse(bridge.activeHooksSettings())
                source = parsed.source || "none"
                settingsText = JSON.stringify(parsed.settings || {}, null, 2)
            } catch (e) {
                source = "none"
                settingsText = "{}"
            }
        }

        implicitHeight: 20
        ToolTip.visible: hovered
        ToolTip.text: qsTr("Hooks: ") + source
        background: Rectangle {
            color: hooksIndicator.hovered ? topbar.theme.codeBg : "transparent"
            border.color: topbar.theme.borderSoft
            border.width: 1
            radius: topbar.theme.radiusSm
        }
        contentItem: Text {
            text: "⚙ " + qsTr("hooks: ") + hooksIndicator.source
            color: hooksIndicator.source === "none" ? topbar.fgDim : topbar.fg
            font.pixelSize: 10
            font.family: topbar.monoFamily
            leftPadding: 6
            rightPadding: 6
            verticalAlignment: Text.AlignVCenter
        }
        onClicked: {
            refresh()
            hooksPopup.open()
        }
        Component.onCompleted: refresh()
    }

    Popup {
        id: hooksPopup
        parent: Overlay.overlay
        x: (parent ? (parent.width - width) / 2 : 0)
        y: 60
        width: 480
        height: 360
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: topbar.theme.codeBg
            border.color: topbar.theme.borderSoft
            border.width: 1
            radius: topbar.theme.radiusSm
        }

        contentItem: ColumnLayout {
            spacing: 6
            Text {
                text: qsTr("Active hooks settings — source: ") + hooksIndicator.source
                color: topbar.fg
                font.pixelSize: 11
                font.family: topbar.monoFamily
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    text: hooksIndicator.settingsText
                    color: topbar.fg
                    font.family: topbar.monoFamily
                    font.pixelSize: 10
                    background: Rectangle { color: "transparent" }
                }
            }
        }
    }

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
