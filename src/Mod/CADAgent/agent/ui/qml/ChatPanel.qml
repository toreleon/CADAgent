// SPDX-License-Identifier: LGPL-2.1-or-later
// CAD Agent chat panel (QML) — Claude Code CLI aesthetic.
//
// Design intent: the panel reads like a terminal transcript. No bubbles,
// no avatars, no gradients. Each row is identified by a leading marker
// glyph ("●" / "⏺" / "✻" / "⎿" / "!") in a narrow gutter, followed by
// flat text in the content column. Tool I/O uses monospace and a tree
// corner ("⎿") to show the result belongs to the call above it.
//
// The Python side (qml_panel.py) exposes two context properties:
//   - bridge:   QmlChatBridge  — slots for send/stop/new/configure/decide
//   - messages: MessagesModel  — QAbstractListModel of chat rows
// Row roles: kind, text, meta.

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: pal.window

    SystemPalette { id: pal; colorGroup: SystemPalette.Active }

    // ── Design tokens ────────────────────────────────────────────────
    readonly property int gutter: 22        // marker column width
    readonly property int rowPadY: 3
    readonly property int radiusSm: 3
    readonly property int radiusMd: 4
    readonly property int fontSm: 11
    readonly property int fontMd: 12
    readonly property color accent: pal.highlight
    readonly property color accentFg: pal.highlightedText
    readonly property color fg: pal.text
    readonly property color fgDim: Qt.rgba(pal.text.r, pal.text.g, pal.text.b, 0.55)
    readonly property color fgMuted: Qt.rgba(pal.text.r, pal.text.g, pal.text.b, 0.40)
    readonly property color border: Qt.rgba(pal.text.r, pal.text.g, pal.text.b, 0.18)
    readonly property color borderSoft: Qt.rgba(pal.text.r, pal.text.g, pal.text.b, 0.10)
    readonly property color codeBg: Qt.rgba(0.5, 0.5, 0.5, 0.12)
    readonly property color okColor: "#5ec270"
    readonly property color errColor: "#e05757"
    readonly property string monoFamily: "Menlo"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Topbar ─────────────────────────────────────────────────────
        // Left: agent indicator + milestone pip. Right: permission-mode
        // chip and glyph action buttons. Everything is borderless, dim by
        // default, lighting up on hover — matching the terminal aesthetic.
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.topMargin: 4
            spacing: 6

            // Current-agent indicator. "main" is hidden to reduce noise;
            // subagent names render as "[reviewer]" in accent.
            Text {
                text: !bridge || bridge.currentAgent === "main" ? "" : "[" + bridge.currentAgent + "]"
                visible: text.length > 0
                color: accent
                font.pixelSize: 10
                font.family: monoFamily
            }

            // Milestone progress pip. Empty string hides it. The runtime
            // updates this via upsert_milestone(), so no QML-side plumbing.
            Text {
                text: bridge ? bridge.milestoneSummary : ""
                visible: text.length > 0
                color: fgDim
                font.pixelSize: 10
                font.family: monoFamily
                elide: Text.ElideRight
                Layout.maximumWidth: 240
            }

            Item { Layout.fillWidth: true }

            // Permission-mode chip → popup menu.
            ToolButton {
                id: permChip
                implicitHeight: 20
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Permission mode")
                onClicked: permMenu.open()
                background: Rectangle {
                    color: "transparent"
                    border.color: permChip.hovered ? border : borderSoft
                    border.width: 1
                    radius: radiusSm
                }
                contentItem: Text {
                    text: {
                        var m = bridge ? bridge.permissionMode : "default"
                        if (m === "bypassPermissions") return "⛨ bypass"
                        if (m === "acceptEdits")       return "✎ auto"
                        if (m === "plan")              return "◆ plan"
                        return "● default"
                    }
                    color: (bridge && bridge.permissionMode === "bypassPermissions") ? errColor
                         : ((bridge && bridge.permissionMode === "plan") ? accent : fgDim)
                    font.pixelSize: 10
                    font.family: monoFamily
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 6
                    rightPadding: 6
                }
                Menu {
                    id: permMenu
                    y: permChip.height
                    Repeater {
                        model: [
                            { mode: "default",          label: qsTr("● default  (prompt per tool)") },
                            { mode: "acceptEdits",      label: qsTr("✎ auto     (accept edits)") },
                            { mode: "plan",             label: qsTr("◆ plan     (read-only planning)") },
                            { mode: "bypassPermissions",label: qsTr("⛨ bypass   (no prompts)") }
                        ]
                        delegate: MenuItem {
                            required property var modelData
                            text: modelData.label
                            onTriggered: bridge.setPermissionMode(modelData.mode)
                        }
                    }
                }
            }

            Repeater {
                model: [
                    { symbol: "＋", tip: qsTr("New chat"),       action: "new" },
                    { symbol: "⟳", tip: qsTr("History"),        action: "history" },
                    { symbol: "⚙", tip: qsTr("Configure LLM"),  action: "config" }
                ]
                delegate: ToolButton {
                    required property var modelData
                    implicitWidth: 24
                    implicitHeight: 24
                    ToolTip.visible: hovered
                    ToolTip.text: modelData.tip
                    onClicked: {
                        if (modelData.action === "new")          bridge.newChat()
                        else if (modelData.action === "history") bridge.showHistory()
                        else if (modelData.action === "config")  bridge.configureLlm()
                    }
                    background: Rectangle { color: "transparent" }
                    contentItem: Text {
                        text: parent.modelData.symbol
                        color: parent.hovered ? fg : fgDim
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        // ── Transcript ────────────────────────────────────────────────
        ListView {
            id: stream
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 0
            Layout.rightMargin: 0
            Layout.topMargin: 2
            clip: true
            spacing: 0
            model: messages
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Loader {
                width: stream.width
                property var rowModel: model
                sourceComponent: {
                    switch (model.kind) {
                        case "user":         return userRow
                        case "assistant":    return assistantRow
                        case "thinking":     return thinkingRow
                        case "system":       return systemRow
                        case "error":        return errorRow
                        case "footer":       return footerRow
                        case "tool":         return toolRow
                        case "perm":         return permRow
                        case "ask":          return askRow
                        case "milestone":    return milestoneRow
                        case "verification": return verificationRow
                        case "decision":     return decisionRow
                        case "compaction":   return compactionRow
                        case "subagent":     return subagentRow
                        default:             return systemRow
                    }
                }
            }

            onCountChanged: Qt.callLater(function () { stream.positionViewAtEnd() })

            Connections {
                target: bridge
                function onScrollToEnd() { stream.positionViewAtEnd() }
            }
        }

        // ── Thinking ticker ──────────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: (bridge && bridge.busy) ? 16 : 0
            visible: bridge && bridge.busy
            Text {
                anchors.left: parent.left
                anchors.leftMargin: gutter
                anchors.verticalCenter: parent.verticalCenter
                text: "✻ " + qsTr("working…")
                color: fgDim
                font.pixelSize: fontSm
                font.italic: true
            }
        }

        // ── Composer ──────────────────────────────────────────────────
        Rectangle {
            id: composer
            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.bottomMargin: 6
            Layout.topMargin: 2
            color: pal.base
            border.color: input.activeFocus ? accent : border
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

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        text: ">"
                        color: input.activeFocus ? accent : fgDim
                        font.family: monoFamily
                        font.pixelSize: fontMd
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 2
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(Math.max(input.implicitHeight, 22), 160)
                        clip: true

                        TextArea {
                            id: input
                            wrapMode: TextEdit.Wrap
                            placeholderText: qsTr("Ask the CAD agent…")
                            background: null
                            color: fg
                            selectByMouse: true
                            font.pixelSize: fontMd
                            Keys.onPressed: function (event) {
                                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                    && (event.modifiers & (Qt.ControlModifier | Qt.MetaModifier))) {
                                    root.submit()
                                    event.accepted = true
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        text: qsTr("Ctrl+Enter to send")
                        color: fgMuted
                        font.pixelSize: 10
                        font.family: monoFamily
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        id: stopBtn
                        visible: bridge && bridge.busy
                        implicitWidth: 22
                        implicitHeight: 22
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("Stop")
                        onClicked: bridge.stop()
                        background: Rectangle {
                            color: "transparent"
                            border.color: stopBtn.hovered ? errColor : border
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
                        implicitWidth: 22
                        implicitHeight: 22
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("Send  (Ctrl+Enter)")
                        onClicked: root.submit()
                        background: Rectangle {
                            color: sendBtn.enabled ? accent : "transparent"
                            border.color: sendBtn.enabled ? accent : border
                            border.width: 1
                            radius: radiusSm
                        }
                        contentItem: Text {
                            text: "↵"
                            color: sendBtn.enabled ? accentFg : fgMuted
                            font.pixelSize: 12
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }
    }

    function submit() {
        var text = input.text.trim()
        if (text.length === 0) return
        input.clear()
        bridge.submit(text)
    }

    // ── Row components ────────────────────────────────────────────────
    //
    // Every row follows the same two-column layout: a narrow gutter with
    // a marker glyph, and a content column with flat text. No bubbles,
    // no frames — rely on typography + whitespace for hierarchy.

    // User message: ">" prompt marker, regular text.
    Component {
        id: userRow
        Item {
            // rowModel is forwarded from the delegate Loader via runtime parent
            // chain. Having it as a root property lets nested children bind to
            // `rowModel.*` through normal QML scope lookup.
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: userText.implicitHeight + rowPadY * 2 + 4
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
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                text: rowModel ? rowModel.text : ""
                color: fg
                wrapMode: Text.Wrap
                font.pixelSize: fontMd
                textFormat: Text.PlainText
            }
        }
    }

    // Assistant message: "⏺" bullet, markdown-rendered content.
    // Shows a dim [agent] prefix when a subagent emitted the row, and a
    // subtle "…" suffix while the row is still being streamed.
    Component {
        id: assistantRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            property string _agent: rowModel && rowModel.meta ? (rowModel.meta.agent || "") : ""
            property bool _partial: rowModel && rowModel.meta ? (rowModel.meta.isPartial === true) : false
            implicitHeight: asstText.implicitHeight + rowPadY * 2 + 4
            Text {
                x: 6
                y: rowPadY + 2
                text: _partial ? "✻" : "⏺"
                color: accent
                font.pixelSize: fontMd
            }
            Text {
                id: agentChip
                visible: _agent.length > 0
                x: gutter
                y: rowPadY + 2
                text: "[" + _agent + "]"
                color: fgDim
                font.pixelSize: fontSm
                font.family: monoFamily
            }
            Text {
                id: asstText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: _agent.length > 0 ? gutter + agentChip.implicitWidth + 6 : gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                text: (rowModel ? rowModel.text : "") + (_partial ? " …" : "")
                color: fg
                wrapMode: Text.Wrap
                textFormat: Text.MarkdownText
                font.pixelSize: fontMd
                onLinkActivated: Qt.openUrlExternally(link)
            }
        }
    }

    // Thinking: "✻" sparkle marker, italic dim.
    Component {
        id: thinkingRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: thinkText.implicitHeight + rowPadY * 2
            Text {
                x: 6
                y: rowPadY
                text: "✻"
                color: fgDim
                font.pixelSize: fontMd
            }
            Text {
                id: thinkText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY
                text: rowModel ? rowModel.text : ""
                color: fgDim
                wrapMode: Text.Wrap
                font.italic: true
                font.pixelSize: fontSm
            }
        }
    }

    // System row: no marker, dim small text flush with content column.
    Component {
        id: systemRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: sysText.implicitHeight + rowPadY * 2
            Text {
                id: sysText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY
                text: rowModel ? rowModel.text : ""
                color: fgDim
                wrapMode: Text.Wrap
                font.pixelSize: fontSm
                font.italic: true
            }
        }
    }

    // Error: "!" marker in error color, no frame.
    Component {
        id: errorRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: errText.implicitHeight + rowPadY * 2 + 2
            Text {
                x: 6
                y: rowPadY + 1
                text: "!"
                color: errColor
                font.bold: true
                font.pixelSize: fontMd
            }
            Text {
                id: errText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 1
                text: rowModel ? rowModel.text : ""
                color: errColor
                wrapMode: Text.Wrap
                font.pixelSize: fontMd
            }
        }
    }

    // Footer: right-aligned dim monospace (tokens · cost).
    Component {
        id: footerRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: 18
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: rowModel ? rowModel.text : ""
                color: fgMuted
                font.pixelSize: 10
                font.family: monoFamily
            }
        }
    }

    // Tool call: "⏺ name(args)" + "⎿ result" tree-corner below.
    Component {
        id: toolRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: toolCol.implicitHeight + rowPadY * 2 + 4

            Text {
                x: 6
                y: rowPadY + 2
                text: "⏺"
                color: rowModel && rowModel.meta && rowModel.meta.isError ? errColor
                       : (rowModel && rowModel.meta && rowModel.meta.status === "OK" ? okColor : accent)
                font.pixelSize: fontMd
            }

            Column {
                id: toolCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 2

                // Header line: "[agent] name(input)". Clickable when the
                // row has verification children — toggles collapse.
                MouseArea {
                    width: toolHeader.implicitWidth
                    height: toolHeader.implicitHeight
                    cursorShape: (rowModel && rowModel.meta
                                  && rowModel.meta.children
                                  && rowModel.meta.children.length > 0)
                                 ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        if (rowModel && rowModel.meta
                            && rowModel.meta.children
                            && rowModel.meta.children.length > 0)
                            bridge.toggleCollapse(rowModel.rowId)
                    }
                    Text {
                        id: toolHeader
                        width: toolCol.width
                        text: {
                            var n = rowModel ? rowModel.text : ""
                            var a = rowModel && rowModel.meta && rowModel.meta.agent
                                    ? "[" + rowModel.meta.agent + "] " : ""
                            var inp = rowModel && rowModel.meta && rowModel.meta.inputPreview
                                      ? rowModel.meta.inputPreview : ""
                            var body = (inp.length === 0) ? (n + "()")
                                     : (inp.indexOf("\n") < 0 ? n + "(" + inp + ")" : n + "(…)")
                            return a + body
                        }
                        color: fg
                        wrapMode: Text.Wrap
                        font.pixelSize: fontMd
                        font.family: monoFamily
                    }
                }

                // Multi-line input (indented, tree corner)
                Row {
                    visible: rowModel && rowModel.meta && rowModel.meta.inputPreview
                             && rowModel.meta.inputPreview.indexOf("\n") >= 0
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        width: toolCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.inputPreview) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // Result (tree corner + preview)
                Row {
                    visible: !!(rowModel && rowModel.meta && rowModel.meta.resultPreview)
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        width: toolCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.resultPreview) || ""
                        color: rowModel && rowModel.meta && rowModel.meta.isError ? errColor : fg
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // "running…" placeholder until a result arrives.
                Row {
                    visible: rowModel && rowModel.meta
                             && !rowModel.meta.resultPreview
                             && rowModel.meta.status === "…"
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        text: qsTr("running…")
                        color: fgMuted
                        font.italic: true
                        font.pixelSize: fontSm
                    }
                }
            }
        }
    }

    // Permission request: "⏺ tool(input)" + inline [Approve] [Reject].
    Component {
        id: permRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: permCol.implicitHeight + rowPadY * 2 + 4

            Text {
                x: 6
                y: rowPadY + 2
                text: "⏺"
                color: rowModel && rowModel.meta && rowModel.meta.pending ? accent : fgMuted
                font.pixelSize: fontMd
            }

            Column {
                id: permCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 4

                Text {
                    width: parent.width
                    text: {
                        var n = rowModel ? rowModel.text : ""
                        var inp = rowModel && rowModel.meta && rowModel.meta.inputPreview
                                  ? rowModel.meta.inputPreview : ""
                        if (inp.length === 0) return n + "()"
                        return inp.indexOf("\n") < 0
                            ? n + "(" + inp + ")"
                            : n + "(…)"
                    }
                    color: fg
                    wrapMode: Text.Wrap
                    font.pixelSize: fontMd
                    font.family: monoFamily
                }

                // Multi-line input (tree corner)
                Row {
                    visible: rowModel && rowModel.meta && rowModel.meta.inputPreview
                             && rowModel.meta.inputPreview.indexOf("\n") >= 0
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        width: permCol.width - 20
                        text: (rowModel && rowModel.meta && rowModel.meta.inputPreview) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                }

                // Action row — inline plain-text buttons, no frames.
                Row {
                    visible: rowModel && rowModel.meta && rowModel.meta.pending
                    spacing: 12
                    topPadding: 2

                    Text {
                        text: qsTr("⎿  approve?")
                        color: fgDim
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }

                    MouseArea {
                        width: approveLabel.width
                        height: approveLabel.height
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.decidePermission(rowModel.meta.reqId, true, "")
                        Text {
                            id: approveLabel
                            text: "[" + qsTr("yes") + "]"
                            color: parent.containsMouse ? okColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                            font.bold: true
                        }
                        hoverEnabled: true
                    }

                    MouseArea {
                        width: rejectLabel.width
                        height: rejectLabel.height
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.decidePermission(rowModel.meta.reqId, false, "")
                        Text {
                            id: rejectLabel
                            text: "[" + qsTr("no") + "]"
                            color: parent.containsMouse ? errColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        hoverEnabled: true
                    }
                }

                // Resolved state — shows the decision, greyed.
                Row {
                    visible: rowModel && rowModel.meta && !rowModel.meta.pending
                    spacing: 6
                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }
                    Text {
                        text: (rowModel && rowModel.meta && rowModel.meta.decision) || ""
                        color: fgMuted
                        font.italic: true
                        font.pixelSize: fontSm
                    }
                }
            }
        }
    }

    // AskUserQuestion card: one block per question, clickable options, and a
    // [submit] [skip] footer. Follows the Claude Code CLI convention —
    // numbered rows with radio/checkbox glyphs, dim descriptions, no frames.
    Component {
        id: askRow
        Item {
            id: askRoot
            property var rowModel: parent ? parent.rowModel : null
            // selections[i] is either an int (single-select) or list[int]
            // (multi-select) of option indexes per question.
            property var selections: []

            function initSelections() {
                var qs = (rowModel && rowModel && rowModel.meta && rowModel.meta.questions) || []
                var out = []
                for (var i = 0; i < qs.length; ++i)
                    out.push(qs[i].multiSelect ? [] : -1)
                selections = out
            }

            Component.onCompleted: initSelections()

            function isSelected(qi, oi) {
                var s = selections[qi]
                if (Array.isArray(s)) return s.indexOf(oi) >= 0
                return s === oi
            }

            function toggle(qi, oi, multi) {
                var next = selections.slice()
                if (multi) {
                    var arr = (Array.isArray(next[qi]) ? next[qi] : []).slice()
                    var pos = arr.indexOf(oi)
                    if (pos >= 0) arr.splice(pos, 1)
                    else arr.push(oi)
                    next[qi] = arr
                } else {
                    next[qi] = (next[qi] === oi ? -1 : oi)
                }
                selections = next
            }

            function buildAnswers() {
                var qs = rowModel.meta.questions
                var out = []
                for (var i = 0; i < qs.length; ++i) {
                    var q = qs[i]
                    var s = selections[i]
                    if (q.multiSelect) {
                        var labels = []
                        if (Array.isArray(s))
                            for (var j = 0; j < s.length; ++j)
                                labels.push(q.options[s[j]].label)
                        out.push({
                            header: q.header || "",
                            selected: labels,
                            skipped: labels.length === 0
                        })
                    } else if (s >= 0) {
                        out.push({
                            header: q.header || "",
                            selected: q.options[s].label,
                            skipped: false
                        })
                    } else {
                        out.push({
                            header: q.header || "",
                            selected: null,
                            skipped: true
                        })
                    }
                }
                return out
            }

            function doSubmit() {
                bridge.submitAnswers(rowModel.meta.askId,
                                     JSON.stringify(buildAnswers()))
            }

            function doSkip() {
                var qs = rowModel.meta.questions
                var out = []
                for (var i = 0; i < qs.length; ++i)
                    out.push({ header: qs[i].header || "", selected: null, skipped: true })
                bridge.submitAnswers(rowModel.meta.askId, JSON.stringify(out))
            }

            implicitHeight: askCol.implicitHeight + rowPadY * 2 + 4

            Text {
                x: 6
                y: rowPadY + 2
                text: "⏺"
                color: rowModel && rowModel && rowModel.meta && rowModel.meta.pending
                       ? accent : fgMuted
                font.pixelSize: fontMd
            }

            Column {
                id: askCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 6

                // One block per question.
                Repeater {
                    model: (askRoot.rowModel && askRoot.rowModel.meta
                            && askRoot.rowModel.meta.questions) || []
                    delegate: Column {
                        width: askCol.width
                        spacing: 3
                        property int questionIndex: index
                        property var q: modelData

                        // Header (bold) + question (regular)
                        Text {
                            width: parent.width
                            text: q.header ? q.header : ""
                            visible: text.length > 0
                            color: fg
                            font.pixelSize: fontMd
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                        Text {
                            width: parent.width
                            text: q.question ? q.question : ""
                            visible: text.length > 0
                            color: fgDim
                            font.pixelSize: fontSm
                            font.italic: true
                            wrapMode: Text.Wrap
                            bottomPadding: 2
                        }

                        // Options list.
                        Repeater {
                            model: q.options || []
                            delegate: MouseArea {
                                width: parent.width
                                height: optRow.implicitHeight + 4
                                hoverEnabled: true
                                cursorShape: askRoot.rowModel && askRoot.rowModel.meta
                                             && askRoot.rowModel.meta.pending
                                             ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: if (askRoot.rowModel && askRoot.rowModel.meta
                                               && askRoot.rowModel.meta.pending)
                                    askRoot.toggle(questionIndex, index, q.multiSelect || false)

                                property int optionIndex: index
                                property bool checked: askRoot.isSelected(questionIndex, optionIndex)

                                Row {
                                    id: optRow
                                    anchors.fill: parent
                                    anchors.topMargin: 2
                                    spacing: 6

                                    // Glyph: ●/○ for single-select, ☑/☐ for multi.
                                    Text {
                                        anchors.top: parent.top
                                        text: q.multiSelect
                                            ? (parent.parent.checked ? "☑" : "☐")
                                            : (parent.parent.checked ? "●" : "○")
                                        color: parent.parent.checked ? accent : fgDim
                                        font.pixelSize: fontMd
                                        width: 14
                                    }

                                    Column {
                                        width: optRow.width - 20
                                        spacing: 0
                                        Text {
                                            width: parent.width
                                            text: modelData.label || ""
                                            color: parent.parent.parent.checked ? fg : fgDim
                                            font.pixelSize: fontMd
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            width: parent.width
                                            text: modelData.description || ""
                                            visible: text.length > 0
                                            color: fgMuted
                                            font.pixelSize: fontSm
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Action row (text-style, matching permission card).
                Row {
                    visible: askRoot.rowModel && askRoot.rowModel.meta
                             && askRoot.rowModel.meta.pending
                    spacing: 14
                    topPadding: 4

                    Text {
                        text: "⎿"
                        color: fgMuted
                        font.pixelSize: fontSm
                        font.family: monoFamily
                    }

                    MouseArea {
                        width: submitLabel.width
                        height: submitLabel.height
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: askRoot.doSubmit()
                        Text {
                            id: submitLabel
                            text: "[" + qsTr("submit") + "]"
                            color: parent.containsMouse ? okColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                            font.bold: true
                        }
                    }

                    MouseArea {
                        width: skipLabel.width
                        height: skipLabel.height
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: askRoot.doSkip()
                        Text {
                            id: skipLabel
                            text: "[" + qsTr("skip") + "]"
                            color: parent.containsMouse ? errColor : fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                    }
                }

                // Resolved state: show the chosen answers, greyed.
                Repeater {
                    model: (askRoot.rowModel && askRoot.rowModel.meta
                            && !askRoot.rowModel.meta.pending
                            && askRoot.rowModel.meta.answers) || []
                    delegate: Row {
                        width: askCol.width
                        spacing: 6
                        Text {
                            text: "⎿"
                            color: fgMuted
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        Text {
                            width: askCol.width - 20
                            text: {
                                var hdr = modelData.header || ""
                                if (modelData.skipped)
                                    return (hdr ? hdr + " → " : "") + qsTr("skipped")
                                var sel = modelData.selected
                                if (Array.isArray(sel)) sel = sel.join(", ")
                                return (hdr ? hdr + " → " : "") + (sel || "")
                            }
                            color: fgDim
                            font.pixelSize: fontSm
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }

    // Milestone banner — "◆ i/N  Title  · status". Planner (Move 2) upserts
    // these; status transitions (pending/active/done/failed) update in place.
    Component {
        id: milestoneRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
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
    }

    // Verification row — PostToolUse hook output indented under the parent
    // tool row. "✓" / "✗" per check, with an optional detail line.
    Component {
        id: verificationRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
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
    }

    // Decision record — "★ title" with collapsible rationale/alternatives.
    Component {
        id: decisionRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            property bool _collapsed: rowModel && rowModel.meta ? (rowModel.meta.collapsed !== false) : true
            implicitHeight: dCol.implicitHeight + rowPadY * 2 + 4
            Text {
                x: 6
                y: rowPadY + 2
                text: "★"
                color: accent
                font.pixelSize: fontMd
            }
            Column {
                id: dCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY + 2
                spacing: 3

                MouseArea {
                    width: dHeader.width
                    height: dHeader.height
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (rowModel) bridge.toggleCollapse(rowModel.rowId)
                    Row {
                        id: dHeader
                        spacing: 6
                        Text {
                            text: _collapsed ? "▸" : "▾"
                            color: fgDim
                            font.pixelSize: fontSm
                            font.family: monoFamily
                        }
                        Text {
                            text: rowModel ? rowModel.text : ""
                            color: fg
                            font.pixelSize: fontMd
                            font.bold: true
                        }
                    }
                }

                Column {
                    visible: !_collapsed
                    width: dCol.width
                    spacing: 2

                    Text {
                        width: parent.width
                        visible: rowModel && rowModel.meta && rowModel.meta.rationale
                                 && rowModel.meta.rationale.length > 0
                        text: (rowModel && rowModel.meta && rowModel.meta.rationale) || ""
                        color: fgDim
                        wrapMode: Text.Wrap
                        font.pixelSize: fontSm
                    }

                    Repeater {
                        model: (rowModel && rowModel.meta && rowModel.meta.alternatives) || []
                        delegate: Row {
                            width: dCol.width
                            spacing: 6
                            Text {
                                text: "·"
                                color: fgMuted
                                font.pixelSize: fontSm
                                width: 8
                            }
                            Text {
                                width: dCol.width - 14
                                text: modelData.label
                                      ? (modelData.label + (modelData.reason ? "  — " + modelData.reason : ""))
                                      : (typeof modelData === "string" ? modelData : "")
                                color: fgDim
                                wrapMode: Text.Wrap
                                font.pixelSize: fontSm
                            }
                        }
                    }

                    Row {
                        visible: (rowModel && rowModel.meta && rowModel.meta.tags
                                  && rowModel.meta.tags.length > 0) || false
                        spacing: 4
                        topPadding: 2
                        Repeater {
                            model: (rowModel && rowModel.meta && rowModel.meta.tags) || []
                            delegate: Rectangle {
                                color: codeBg
                                radius: radiusSm
                                implicitHeight: tagText.implicitHeight + 2
                                implicitWidth: tagText.implicitWidth + 8
                                Text {
                                    id: tagText
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: fgDim
                                    font.pixelSize: 10
                                    font.family: monoFamily
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Compaction breadcrumb — dim single-line "≡ compacted N→M · archive".
    Component {
        id: compactionRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            implicitHeight: cText.implicitHeight + rowPadY * 2
            Text {
                x: 6
                y: rowPadY
                text: "≡"
                color: fgMuted
                font.pixelSize: fontMd
            }
            Text {
                id: cText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: gutter
                anchors.rightMargin: 12
                y: rowPadY
                text: {
                    var m = rowModel && rowModel.meta ? rowModel.meta : {}
                    var head = qsTr("compacted")
                    var tok = ""
                    if (typeof m.tokensBefore === "number" || typeof m.tokensAfter === "number") {
                        var b = m.tokensBefore != null ? m.tokensBefore.toLocaleString() : "?"
                        var a = m.tokensAfter  != null ? m.tokensAfter.toLocaleString()  : "?"
                        tok = "  " + b + " → " + a + " tok"
                    }
                    var arch = m.archivePath ? "  · " + m.archivePath : ""
                    return head + tok + arch
                }
                color: fgMuted
                wrapMode: Text.NoWrap
                elide: Text.ElideMiddle
                font.italic: true
                font.pixelSize: fontSm
                font.family: monoFamily
            }
        }
    }

    // Subagent span marker — a faint rule showing delegation start/end.
    // All rows between a start/end pair already carry meta.agent via the
    // MessagesModel, which the shared [agent] prefix logic picks up.
    Component {
        id: subagentRow
        Item {
            property var rowModel: parent ? parent.rowModel : null
            property string _action: rowModel && rowModel.meta ? (rowModel.meta.action || "start") : "start"
            property string _agent: rowModel && rowModel.meta ? (rowModel.meta.agent  || "")    : ""
            implicitHeight: 18
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Text {
                    text: _action === "start" ? "┌" : "└"
                    color: fgMuted
                    font.family: monoFamily
                    font.pixelSize: fontSm
                }
                Text {
                    text: _action === "start"
                        ? (qsTr("→ delegate") + "  [" + _agent + "]"
                           + (rowModel && rowModel.text ? "  " + rowModel.text : ""))
                        : (qsTr("← return") + "  [" + _agent + "]")
                    color: fgDim
                    font.pixelSize: fontSm
                    font.italic: true
                    font.family: monoFamily
                }
            }
        }
    }
}
