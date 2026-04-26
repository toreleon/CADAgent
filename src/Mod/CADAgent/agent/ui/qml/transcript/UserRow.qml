// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

        Item {
            id: userRoot
            // rowModel is forwarded from the delegate Loader via runtime parent
            // chain. Having it as a root property lets nested children bind to
            // `rowModel.*` through normal QML scope lookup.
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

    readonly property string _rowId: rowModel ? (rowModel.rowId || "") : ""
    readonly property string _text: rowModel ? (rowModel.text || "") : ""

            implicitHeight: userText.implicitHeight + rowPadY * 2 + 4

            HoverHandler { id: userHover }

            Text {
                id: userMark
                x: 6
                y: rowPadY + 2
                text: ">"
                color: fgDim
                font.family: monoFamily
                font.pixelSize: fontMd
            }
            Text {
                id: userText
                anchors.left: parent.left
                anchors.right: rewindBtn.left
                anchors.leftMargin: gutter
                anchors.rightMargin: 8
                y: rowPadY + 2
                text: _text
                color: fg
                wrapMode: Text.Wrap
                font.pixelSize: fontMd
                textFormat: Text.PlainText
            }

            RewindButton {
                id: rewindBtn
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.top: parent.top
                anchors.topMargin: rowPadY
                theme: userRoot.theme
                active: userHover.hovered && _rowId.length > 0 && bridge !== null
                onRewindClicked: {
                    if (bridge && _rowId.length > 0)
                        bridge.requestRewind(_rowId, false, "")
                }
                onForkClicked: editOverlay.openWith(_text, true)
                onEditClicked: editOverlay.openWith(_text, false)
            }

            MessageEditOverlay {
                id: editOverlay
                theme: userRoot.theme
                onSubmitted: function (newText, asFork) {
                    if (bridge && _rowId.length > 0)
                        bridge.requestRewind(_rowId, asFork, newText)
                }
            }
        }
