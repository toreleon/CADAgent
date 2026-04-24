// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: composerRoot

    property var bridge
    property var theme
    signal submitted(string text)

    readonly property int radiusSm: theme.radiusSm
    readonly property int radiusMd: theme.radiusMd
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property color accent: theme.accent
    readonly property color accentFg: theme.accentFg
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property color fgMuted: theme.fgMuted
    readonly property color borderColor: theme.border
    readonly property color borderSoft: theme.borderSoft
    readonly property color errColor: theme.errColor
    readonly property string monoFamily: theme.monoFamily

    color: theme.pal.base
    border.color: input.activeFocus
                ? accent
                : (bridge && bridge.permissionMode === "bypassPermissions"
                   ? Qt.rgba(errColor.r, errColor.g, errColor.b, 0.45)
                   : (bridge && bridge.permissionMode === "plan"
                      ? Qt.rgba(accent.r, accent.g, accent.b, 0.45)
                      : composerRoot.borderColor))
    border.width: 1
    radius: radiusMd
    implicitHeight: compLayout.implicitHeight + 14

    ColumnLayout {
        id: compLayout
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 6
        anchors.topMargin: 6
        anchors.bottomMargin: 6
        spacing: 4

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(Math.max(input.implicitHeight, 22), 160)
            clip: true

            TextArea {
                id: input
                wrapMode: TextEdit.Wrap
                placeholderText: qsTr("Ask the CAD agent… (Enter to send, Shift+Enter for newline)")
                background: null
                color: fg
                selectByMouse: true
                font.pixelSize: fontMd
                Keys.onPressed: function (event) {
                    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        if (event.modifiers & Qt.ShiftModifier) {
                            return
                        }
                        var text = input.text.trim()
                        if (text.length > 0 || (bridge && bridge.attachmentsJson !== "[]")) {
                            input.clear()
                            composerRoot.submitted(text)
                        }
                        event.accepted = true
                        return
                    }
                    if (event.key === Qt.Key_V
                        && (event.modifiers & Qt.ControlModifier)
                        && !(event.modifiers & Qt.ShiftModifier)) {
                        if (bridge && bridge.tryPasteImage()) {
                            event.accepted = true
                            return
                        }
                    }
                    if (event.key === Qt.Key_Backtab
                        || (event.key === Qt.Key_Tab
                            && (event.modifiers & Qt.ShiftModifier))) {
                        theme.cycleMode()
                        event.accepted = true
                    }
                }
            }
        }

        Flow {
            id: attachmentsRow
            Layout.fillWidth: true
            spacing: 4
            visible: attachmentsModel.count > 0

            property var items: []
            function refresh() {
                var json = bridge ? bridge.attachmentsJson : "[]"
                try {
                    attachmentsRow.items = JSON.parse(json)
                } catch (e) {
                    attachmentsRow.items = []
                }
                attachmentsModel.clear()
                for (var i = 0; i < attachmentsRow.items.length; ++i) {
                    attachmentsModel.append(attachmentsRow.items[i])
                }
            }

            ListModel { id: attachmentsModel }

            Connections {
                target: bridge
                function onAttachmentsChanged() { attachmentsRow.refresh() }
            }
            Component.onCompleted: attachmentsRow.refresh()

            Repeater {
                model: attachmentsModel
                delegate: Rectangle {
                    radius: radiusSm
                    color: Qt.rgba(accent.r, accent.g, accent.b, 0.10)
                    border.color: borderSoft
                    border.width: 1
                    implicitHeight: 20
                    implicitWidth: chipRow.implicitWidth + 10
                    RowLayout {
                        id: chipRow
                        anchors.fill: parent
                        anchors.leftMargin: 5
                        anchors.rightMargin: 2
                        spacing: 4
                        Text {
                            text: "🖼 " + (model.name || "image")
                            color: fg
                            font.pixelSize: fontSm
                            Layout.alignment: Qt.AlignVCenter
                        }
                        ToolButton {
                            implicitWidth: 16
                            implicitHeight: 16
                            onClicked: bridge.removeAttachment(model.path)
                            background: Rectangle { color: "transparent" }
                            contentItem: Text {
                                text: "✕"
                                color: fgDim
                                font.pixelSize: 10
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            ToolButton {
                id: composerNewBtn
                implicitWidth: 22
                implicitHeight: 22
                ToolTip.visible: hovered
                ToolTip.text: qsTr("New chat")
                onClicked: bridge.newChat()
                background: Rectangle { color: "transparent" }
                contentItem: Text {
                    text: "＋"
                    color: composerNewBtn.hovered ? fg : fgDim
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            ToolButton {
                id: composerSlashBtn
                implicitWidth: 22
                implicitHeight: 22
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Insert slash command")
                onClicked: {
                    if (!input.text.startsWith("/")) {
                        input.insert(0, "/")
                    }
                    input.forceActiveFocus()
                    input.cursorPosition = input.text.length
                }
                background: Rectangle { color: "transparent" }
                contentItem: Text {
                    text: "/"
                    color: composerSlashBtn.hovered ? fg : fgDim
                    font.pixelSize: 12
                    font.family: monoFamily
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Item { Layout.fillWidth: true }

            ToolButton {
                id: permChip
                implicitHeight: 22
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Permission mode  (⇧+Tab to cycle)")
                onClicked: modesPopup.open()
                background: Rectangle {
                    color: bridge && bridge.permissionMode === "bypassPermissions"
                           ? Qt.rgba(errColor.r, errColor.g, errColor.b, 0.10)
                           : bridge && bridge.permissionMode === "plan"
                           ? Qt.rgba(accent.r, accent.g, accent.b, 0.10)
                           : "transparent"
                    border.color: permChip.hovered
                                ? theme.modeColor(bridge ? bridge.permissionMode : "default")
                                : borderSoft
                    border.width: 1
                    radius: radiusSm
                }
                contentItem: Text {
                    text: (bridge ? theme.modeIcon(bridge.permissionMode) : "●")
                          + " "
                          + (bridge ? theme.modeTitle(bridge.permissionMode)
                                    : qsTr("Ask before edits"))
                    color: theme.modeColor(bridge ? bridge.permissionMode : "default")
                    font.pixelSize: 10
                    font.family: monoFamily
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                    rightPadding: 8
                }
            }

            Button {
                id: stopBtn
                visible: bridge && bridge.busy
                implicitWidth: 24
                implicitHeight: 24
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Stop")
                onClicked: bridge.stop()
                background: Rectangle {
                    color: "transparent"
                    border.color: stopBtn.hovered ? errColor : composerRoot.borderColor
                    border.width: 1
                    radius: radiusSm
                }
                contentItem: Text {
                    text: "■"
                    color: stopBtn.hovered ? errColor : fgDim
                    font.pixelSize: 9
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                id: sendBtn
                visible: !bridge || !bridge.busy
                enabled: input.text.trim().length > 0
                         || (bridge && bridge.attachmentsJson !== "[]")
                implicitWidth: 24
                implicitHeight: 24
                readonly property color fillColor:
                    (bridge && bridge.permissionMode === "bypassPermissions")
                        ? errColor : accent
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Send  (Enter)")
                onClicked: {
                    var text = input.text.trim()
                    if (text.length > 0 || (bridge && bridge.attachmentsJson !== "[]")) {
                        input.clear()
                        composerRoot.submitted(text)
                    }
                }
                background: Rectangle {
                    color: sendBtn.enabled ? sendBtn.fillColor : "transparent"
                    border.color: sendBtn.enabled ? sendBtn.fillColor : composerRoot.borderColor
                    border.width: 1
                    radius: radiusSm
                }
                contentItem: Text {
                    text: "↑"
                    color: sendBtn.enabled ? accentFg : fgMuted
                    font.pixelSize: 13
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    ModesPopup {
        id: modesPopup
        bridge: composerRoot.bridge
        theme: composerRoot.theme
        anchorItem: permChip
        panelItem: composerRoot
        panelWidth: composerRoot.width
        panelHeight: composerRoot.height
    }
}
