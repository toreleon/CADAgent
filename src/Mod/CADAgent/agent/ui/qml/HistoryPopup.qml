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
        width: Math.min(420, panelWidth - 12)
        height: Math.min(480, Math.max(160, historyList.contentHeight + 96))
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property var roots: []
        property string filterText: ""
        property bool showArchived: false
        property string editingId: ""

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
                roots = JSON.parse(bridge.listSessions() || "[]")
            } catch (e) {
                roots = []
            }
            filterText = ""
            searchField.text = ""
            editingId = ""
        }

        function _matches(entry, q) {
            var t = ((entry.title || "") + " " + (entry.first_prompt || "")).toLowerCase()
            return t.indexOf(q) !== -1
        }

        function _flatten() {
            var q = filterText ? filterText.toLowerCase() : ""
            var out = []
            for (var i = 0; i < roots.length; ++i) {
                var r = roots[i]
                var children = r.children || []
                var filteredChildren = []
                for (var j = 0; j < children.length; ++j) {
                    var c = children[j]
                    if (!showArchived && c.archived) continue
                    if (q && !_matches(c, q)) continue
                    filteredChildren.push(c)
                }
                var rootMatches = (showArchived || !r.archived) && (!q || _matches(r, q))
                if (!rootMatches && filteredChildren.length === 0) continue
                if (rootMatches) {
                    out.push({ entry: r, depth: 0 })
                } else {
                    // Show parent as a placeholder so children have context
                    out.push({ entry: r, depth: 0, ghost: true })
                }
                for (var k = 0; k < filteredChildren.length; ++k) {
                    out.push({ entry: filteredChildren[k], depth: 1 })
                }
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

            // Search field + archived toggle
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                color: "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 6
                    spacing: 6
                    Text {
                        text: "⌕"
                        color: fgMuted
                        font.pixelSize: fontMd
                    }
                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: qsTr("Filter sessions…")
                        color: fg
                        placeholderTextColor: fgMuted
                        background: Rectangle { color: "transparent" }
                        selectByMouse: true
                        font.pixelSize: fontMd
                        onTextChanged: historyPopup.filterText = text
                    }
                    ToolButton {
                        implicitWidth: 24
                        implicitHeight: 24
                        checkable: true
                        checked: historyPopup.showArchived
                        ToolTip.visible: hovered
                        ToolTip.text: historyPopup.showArchived
                            ? qsTr("Hide archived")
                            : qsTr("Show archived")
                        background: Rectangle {
                            color: parent.checked
                                ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.10)
                                : "transparent"
                            radius: 4
                        }
                        contentItem: Text {
                            text: "▼"
                            color: parent.checked ? fg : fgMuted
                            font.pixelSize: fontSm
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onToggled: historyPopup.showArchived = checked
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
                visible: historyPopup._flatten().length === 0
            }

            ListView {
                id: historyList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                visible: historyPopup._flatten().length > 0
                model: historyPopup._flatten()
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    required property var modelData
                    property var entry: modelData.entry
                    property int depth: modelData.depth || 0
                    property bool ghost: modelData.ghost === true
                    property bool rowHovered: rowMouse.containsMouse
                    property bool isEditing: historyPopup.editingId === entry.id
                    width: historyList.width
                    height: 40
                    color: rowHovered && !ghost
                        ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                        : "transparent"
                    opacity: ghost ? 0.5 : (entry.archived ? 0.65 : 1.0)

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: ghost ? Qt.ArrowCursor : Qt.PointingHandCursor
                        enabled: !ghost && !parent.isEditing
                        onClicked: {
                            bridge.openSession(entry.id)
                            historyPopup.close()
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12 + (depth * 16)
                        anchors.rightMargin: 6
                        spacing: 6

                        Text {
                            visible: depth > 0
                            text: "↳"
                            color: fgMuted
                            font.pixelSize: fontSm
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: !parent.parent.isEditing
                            text: (entry.title || (entry.id || "").slice(0, 8))
                                + (entry.archived ? " " + qsTr("(archived)") : "")
                                + (entry.branch_from_turn !== null && entry.branch_from_turn !== undefined
                                    ? "  · @" + entry.branch_from_turn : "")
                            color: fg
                            font.pixelSize: fontMd
                            elide: Text.ElideRight
                        }

                        TextField {
                            id: renameField
                            Layout.fillWidth: true
                            visible: parent.parent.isEditing
                            text: entry.title || ""
                            color: fg
                            font.pixelSize: fontMd
                            selectByMouse: true
                            background: Rectangle {
                                color: "transparent"
                                border.color: borderColor
                                border.width: 1
                                radius: 3
                            }
                            onAccepted: {
                                bridge.renameSession(entry.id, text)
                                historyPopup.editingId = ""
                                historyPopup.refresh()
                            }
                            Keys.onEscapePressed: {
                                historyPopup.editingId = ""
                            }
                        }

                        Text {
                            visible: !parent.parent.isEditing
                            text: historyPopup._relative(entry.updated_at)
                            color: fgMuted
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }

                        ToolButton {
                            implicitWidth: 22
                            implicitHeight: 22
                            visible: !ghost && (rowMouse.containsMouse || hovered) && !parent.parent.isEditing
                            ToolTip.visible: hovered
                            ToolTip.text: qsTr("Rename")
                            background: Rectangle { color: "transparent" }
                            contentItem: Text {
                                text: "✎"
                                color: parent.hovered ? fg : fgMuted
                                font.pixelSize: fontMd
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: historyPopup.editingId = entry.id
                        }

                        ToolButton {
                            implicitWidth: 22
                            implicitHeight: 22
                            visible: !ghost && (rowMouse.containsMouse || hovered) && !parent.parent.isEditing
                            ToolTip.visible: hovered
                            ToolTip.text: entry.archived ? qsTr("Unarchive") : qsTr("Archive")
                            background: Rectangle { color: "transparent" }
                            contentItem: Text {
                                text: entry.archived ? "▲" : "⤓"
                                color: parent.hovered ? fg : fgMuted
                                font.pixelSize: fontMd
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                if (entry.archived) {
                                    bridge.unarchiveSession(entry.id)
                                } else {
                                    bridge.archiveSession(entry.id)
                                }
                                historyPopup.refresh()
                            }
                        }

                        ToolButton {
                            implicitWidth: 22
                            implicitHeight: 22
                            ToolTip.visible: hovered
                            ToolTip.text: qsTr("Delete session")
                            visible: !ghost && (rowMouse.containsMouse || hovered) && !parent.parent.isEditing
                            background: Rectangle { color: "transparent" }
                            contentItem: Text {
                                text: "🗑"
                                color: parent.hovered ? errColor : fgMuted
                                font.pixelSize: fontMd
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                bridge.deleteSession(entry.id)
                                historyPopup.refresh()
                            }
                        }
                    }
                }
            }
        }
    }
