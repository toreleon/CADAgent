// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Popup {
    id: modesPopup

    property var bridge
    property var theme
    property Item anchorItem
    property Item panelItem
    property real panelWidth: 360
    property real panelHeight: 0

    readonly property int radiusMd: theme.radiusMd
    readonly property int fontSm: theme.fontSm
    readonly property int fontMd: theme.fontMd
    readonly property color fg: theme.fg
    readonly property color fgMuted: theme.fgMuted
    readonly property color borderColor: theme.border
    readonly property color borderSoft: theme.borderSoft
    readonly property string monoFamily: theme.monoFamily
        width: Math.min(360, panelWidth - 12)
        height: modesColumn.implicitHeight + 14
        padding: 0
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        x: {
            if (!anchorItem) return 6
            var p = anchorItem.mapToItem(panelItem, 0, 0)
            return Math.max(6, Math.min(panelWidth - width - 6,
                                        p.x + anchorItem.width - width))
        }
        y: {
            if (!anchorItem) return panelHeight - height - 60
            var p = anchorItem.mapToItem(panelItem, 0, 0)
            return p.y - height - 6
        }

        background: Rectangle {
            color: theme.pal.window
            border.color: borderColor
            border.width: 1
            radius: radiusMd
        }

        contentItem: ColumnLayout {
            id: modesColumn
            anchors.fill: parent
            spacing: 0

            // Header: "Modes" left, "⇧+tab to switch" right.
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 6
                Text {
                    text: qsTr("Modes")
                    color: fg
                    font.pixelSize: fontMd
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: qsTr("⇧+tab to switch")
                    color: fgMuted
                    font.pixelSize: 10
                    font.family: monoFamily
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: borderSoft
            }

            Repeater {
                model: theme.modeDefs
                delegate: Rectangle {
                    id: modeDelegate
                    required property var modelData
                    readonly property bool selected: bridge && bridge.permissionMode === modelData.mode
                    Layout.fillWidth: true
                    Layout.preferredHeight: 52
                    color: modeMouse.containsMouse
                           ? Qt.rgba(theme.pal.text.r, theme.pal.text.g, theme.pal.text.b, 0.06)
                           : "transparent"

                    MouseArea {
                        id: modeMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            bridge.setPermissionMode(modeDelegate.modelData.mode)
                            modesPopup.close()
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 10

                        Text {
                            text: modeDelegate.modelData.icon
                            color: theme.modeColor(modeDelegate.modelData.mode)
                            font.pixelSize: 16
                            Layout.alignment: Qt.AlignVCenter
                            Layout.preferredWidth: 18
                            horizontalAlignment: Text.AlignHCenter
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                text: modeDelegate.modelData.title
                                color: fg
                                font.pixelSize: fontMd
                                font.bold: modeDelegate.selected
                            }
                            Text {
                                text: modeDelegate.modelData.desc
                                color: fgMuted
                                font.pixelSize: fontSm
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                        Text {
                            text: "✓"
                            color: theme.modeColor(modeDelegate.modelData.mode)
                            font.pixelSize: fontMd
                            visible: modeDelegate.selected
                        }
                    }
                }
            }
        }
    }
