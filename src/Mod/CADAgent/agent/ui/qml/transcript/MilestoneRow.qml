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

            property string _status: rowModel && rowModel.meta ? (rowModel.meta.status || "pending") : "pending"
            implicitHeight: msText.implicitHeight + rowPadY * 2 + 6
            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 2
                anchors.bottomMargin: 2
                color: Qt.rgba(accent.r, accent.g, accent.b,
                               _status === "active" ? 0.08 : 0.03)
                border.color: borderSoft
                border.width: 0
                radius: radiusSm
            }
            Text {
                id: msMark
                x: 6
                y: rowPadY + 2
                text: "◆"
                color: _status === "failed" ? errColor
                     : (_status === "done"  ? okColor
                     : (_status === "active" ? accent : fgDim))
                font.pixelSize: fontMd
            }
            Text {
                id: msText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                text: {
                    var m = rowModel && rowModel.meta ? rowModel.meta : {}
                    var pref = ""
                    if (typeof m.index === "number" && typeof m.total === "number")
                        pref = m.index + "/" + m.total + "  "
                    var t = rowModel ? rowModel.text : ""
                    var badge = _status === "active" ? "" : ("  · " + _status)
                    return pref + t + badge
                }
                color: _status === "failed" ? errColor
                     : (_status === "done" ? fgDim : fg)
                wrapMode: Text.Wrap
                font.pixelSize: fontMd
                font.bold: _status === "active"
            }
        }
