// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

ListView {
    id: stream

    property var bridge
    property var messages
    property var theme

    clip: true
    spacing: 0

    function rowSource(kind) {
        switch (kind) {
            case "user":         return "transcript/UserRow.qml"
            case "assistant":    return "transcript/AssistantRow.qml"
            case "thinking":     return "transcript/ThinkingRow.qml"
            case "system":       return "transcript/SystemRow.qml"
            case "error":        return "transcript/ErrorRow.qml"
            case "footer":       return "transcript/FooterRow.qml"
            case "tool":         return "transcript/ToolRow.qml"
            case "perm":         return "transcript/PermissionRow.qml"
            case "ask":          return "transcript/AskRow.qml"
            case "milestone":    return "transcript/MilestoneRow.qml"
            case "todos":        return "transcript/TodosRow.qml"
            case "verification": return "transcript/VerificationRow.qml"
            case "decision":     return "transcript/DecisionRow.qml"
            case "compaction":   return "transcript/CompactionRow.qml"
            case "subagent":     return "transcript/SubagentRow.qml"
            default:             return "transcript/SystemRow.qml"
        }
    }

    model: messages
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    delegate: Loader {
        width: stream.width
        property var rowModel: model
        property var bridge: stream.bridge
        property var theme: stream.theme
        source: stream.rowSource(model.kind)
        onLoaded: {
            item.rowModel = Qt.binding(function () { return rowModel })
            item.bridge = Qt.binding(function () { return bridge })
            item.theme = Qt.binding(function () { return theme })
        }
    }

    onCountChanged: Qt.callLater(function () { stream.positionViewAtEnd() })

    Connections {
        target: stream.bridge
        function onScrollToEnd() { stream.positionViewAtEnd() }
    }
}
