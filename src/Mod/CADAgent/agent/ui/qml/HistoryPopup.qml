// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Popup {
    id: historyPopup

    property var bridge
    property var theme
    property Item anchorItem
    property Item panelItem
    property real panelWidth: 360

    readonly property int radiusMd: theme.radiusMd
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property color fg: theme.fg
    readonly property color fgDim: theme.fgDim
    readonly property color fgMuted: theme.fgMuted
    readonly property color borderColor: theme.border
    readonly property color borderSoft: theme.borderSoft
    readonly property color errColor: theme.errColor
    readonly property string monoFamily: theme.monoFamily
        x: {
            if (!anchorItem) return 0
            var p = anchorItem.mapToItem(panelItem, 0, 0)
            return Math.max(6, p.x + anchorItem.width - width)
        }
        y: {
            if (!anchorItem) return 24
            var p = anchorItem.mapToItem(panelItem, 0, 0)
            return p.y + anchorItem.height + 4
        }
        width: Math.min(360, panelWidth - 12)
        height: Math.min(420, Math.max(120, historyList.contentHeight + 72))
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property var entries: []
        property string filterText: ""

        function _relative(isoStr) {
            if (!isoStr) return ""
            var t = Date.parse(isoStr)
            if (isNaN(t)) return ""
            var dt = (Date.now() - t) / 1000
            if (dt < 60)         return qsTr("now")
            if (dt < 3600)       return Math.floor(dt / 60) + qsTr("m")
            if (dt < 86400)      return Math.floor(dt / 3600) + qsTr("h")
            if (dt < 86400 * 30) return Math.floor(dt / 86400) + qsTr("d")
            return Math.floor(dt / (86400 * 30)) + qsTr("mo")
        }

        function refresh() {
            try {
                entries = JSON.parse(bridge.listSessions() || "[]")
            } catch (e) {
                entries = []
            }
            filterText = ""
            searchField.text = ""
        }

        function _filtered() {
            if (!filterText) return entries
            var q = filterText.toLowerCase()
            var out = []
            for (var i = 0; i < entries.length; ++i) {
                var e = entries[i]
                var t = ((e.title || "") + " " + (e.first_prompt || "")).toLowerCase()
                if (t.indexOf(q) !== -1) out.push(e)
            }
            return out
        }

        background: Rectangle {
            color: theme.pal.window
            border.color: borderColor
            border.width: 1
            radius: radiusMd
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Search field
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                color: "transparent"
                border.color: borderSoft
                border.width: 0
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 6
                    Text {
                        text: "⌕"
                        color: fgMuted
                        font.pixelSize: fontMd
                    }
                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: qsTr("Search sessions…")
                        color: fg
                        placeholderTextColor: fgMuted
                        background: Rectangle { color: "transparent" }
                        selectByMouse: true
                        font.pixelSize: fontMd
                        onTextChanged: historyPopup.filterText = text
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: borderSoft
            }

            // Empty state
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 24
                Layout.bottomMargin: 24
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("No prior sessions.")
                color: fgMuted
                font.pixelSize: fontSm
                visible: historyPopup._filtered().length === 0
            }

            ListView {
                id: historyList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                visible: historyPopup._filtered().length > 0
                model: historyPopup._filtered()
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    required property var modelData
                    property bool rowHovered: rowMouse.containsMouse
                    width: historyList.width
                    height: 40
                    color: rowHovered ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                                      : "transparent"

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            bridge.openSession(modelData.id)
                            historyPopup.close()
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 8
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: modelData.title || (modelData.id || "").slice(0, 8)
                            color: fg
                            font.pixelSize: fontMd
                            elide: Text.ElideRight
                        }
                        Text {
                            text: historyPopup._relative(modelData.updated_at)
                            color: fgMuted
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        ToolButton {
                            implicitWidth: 22
                            implicitHeight: 22
                            ToolTip.visible: hovered
                            ToolTip.text: qsTr("Delete session")
                            visible: rowMouse.containsMouse || hovered
                            background: Rectangle { color: "transparent" }
                            contentItem: Text {
                                text: "🗑"
                                color: parent.hovered ? errColor : fgMuted
                                font.pixelSize: fontMd
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                bridge.deleteSession(modelData.id)
                                historyPopup.refresh()
                            }
                        }
                    }
                }
            }
        }
    }
