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

            property bool _ok: rowModel && rowModel.meta ? (rowModel.meta.ok !== false) : true
            implicitHeight: vCol.implicitHeight + rowPadY * 2
            Text {
                x: gutter - 6
                y: rowPadY
                text: "⎿"
                color: fgMuted
                font.family: monoFamily
                font.pixelSize: fontSm
            }
            Column {
                id: vCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter + 12
                anchors.rightMargin: 12
                y: rowPadY
                spacing: 1
                Repeater {
                    model: (rowModel && rowModel.meta && rowModel.meta.checks) || []
                    delegate: Row {
                        spacing: 6
                        Text {
                            text: (modelData.ok === false) ? "✗" : "✓"
                            color: (modelData.ok === false) ? errColor : okColor
                            font.pixelSize: fontSm
                            font.family: monoFamily
                            width: 10
                        }
                        Text {
                            text: (modelData.name || "") +
                                  (modelData.detail ? "  — " + modelData.detail : "")
                            color: (modelData.ok === false) ? errColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                            wrapMode: Text.Wrap
                            width: vCol.width - 20
                        }
                    }
                }
            }
        }
