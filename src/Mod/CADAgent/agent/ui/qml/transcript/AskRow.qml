// SPDX-License-Identifier: LGPL-2.1-or-later

import QtQuick 2.15
import QtQuick.Controls.Basic 2.15
import QtQuick.Layouts 1.15

        Item {
            id: askRoot
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
