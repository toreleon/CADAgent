// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15

Row {
    id: root

    property var theme: null
    property bool active: false

    signal rewindClicked()
    signal forkClicked()
    signal editClicked()

    spacing: 4
    visible: active

    readonly property color _fg: theme ? theme.fgDim : "#888"
    readonly property color _hoverBg: theme ? theme.codeBg : "#22808080"
    readonly property color _border: theme ? theme.borderSoft : "#33808080"
    readonly property int _fontSm: theme ? theme.fontSm : 11
    readonly property int _radius: theme ? theme.radiusSm : 3

    component IconButton: Rectangle {
        property string label: ""
        property string tip: ""
        signal clicked()

        width: btnText.implicitWidth + 10
        height: btnText.implicitHeight + 4
        radius: _radius
        color: btnHover.hovered ? _hoverBg : "transparent"
        border.color: btnHover.hovered ? _border : "transparent"
        border.width: 1

        Text {
            id: btnText
            anchors.centerIn: parent
            text: label
            color: _fg
            font.pixelSize: _fontSm
            font.family: theme ? theme.monoFamily : "Menlo"
        }

        HoverHandler { id: btnHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: parent.clicked() }
        ToolTip.visible: btnHover.hovered && tip.length > 0
        ToolTip.text: tip
        ToolTip.delay: 400
    }

    IconButton {
        label: "✎"
        tip: qsTr("Edit and resend")
        onClicked: root.editClicked()
    }
    IconButton {
        label: "↺"
        tip: qsTr("Rewind here (truncate)")
        onClicked: root.rewindClicked()
    }
    IconButton {
        label: "⑃"
        tip: qsTr("Fork from here (branch)")
        onClicked: root.forkClicked()
    }
}
