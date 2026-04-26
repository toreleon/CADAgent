// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Popup {
    id: root

    property var theme: null
    property string originalText: ""
    property bool fork: false

    signal submitted(string newText, bool fork)
    signal cancelled()

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    parent: Overlay.overlay
    anchors.centerIn: Overlay.overlay
    width: Math.min((parent ? parent.width : 600) - 32, 520)
    padding: 0

    background: Rectangle {
        radius: theme ? theme.radiusMd : 4
        color: theme ? theme.pal.window : "#202020"
        border.color: theme ? theme.border : "#444"
        border.width: 1
    }

    function openWith(text, asFork) {
        originalText = text || ""
        fork = !!asFork
        editor.text = originalText
        open()
        editor.forceActiveFocus()
        editor.selectAll()
    }

    onClosed: {
        if (!_submitted)
            cancelled()
        _submitted = false
    }

    property bool _submitted: false

    contentItem: ColumnLayout {
        spacing: 8

        Text {
            text: root.fork
                  ? qsTr("Fork from this message")
                  : qsTr("Rewind and edit")
            color: theme ? theme.fg : "#eee"
            font.pixelSize: theme ? theme.fontMd : 12
            font.bold: true
            Layout.margins: 12
            Layout.bottomMargin: 0
        }

        Text {
            text: root.fork
                  ? qsTr("Submit a new prompt; the original branch is preserved.")
                  : qsTr("Submit replaces this message and discards the rest of the turn.")
            color: theme ? theme.fgDim : "#aaa"
            font.pixelSize: theme ? theme.fontSm : 11
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            radius: theme ? theme.radiusSm : 3
            color: theme ? theme.codeBg : "#181818"
            border.color: theme ? theme.borderSoft : "#333"
            border.width: 1

            ScrollView {
                anchors.fill: parent
                anchors.margins: 6
                TextArea {
                    id: editor
                    wrapMode: TextArea.Wrap
                    color: theme ? theme.fg : "#eee"
                    font.pixelSize: theme ? theme.fontMd : 12
                    background: null
                    selectByMouse: true
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            Layout.topMargin: 0
            spacing: 8
            Item { Layout.fillWidth: true }

            Button {
                text: qsTr("Cancel")
                onClicked: root.close()
            }
            Button {
                text: root.fork ? qsTr("Fork") : qsTr("Submit")
                enabled: editor.text.trim().length > 0
                onClicked: {
                    var t = editor.text
                    root._submitted = true
                    root.submitted(t, root.fork)
                    root.close()
                }
            }
        }
    }
}
