# SPDX-License-Identifier: LGPL-2.1-or-later

IF (BUILD_GUI)
    PYSIDE_WRAP_RC(CADAgent_QRC_SRCS Resources/CADAgent.qrc)
ENDIF (BUILD_GUI)

SET(CADAgent_TOP
    InitGui.py
    CADAgent.py
)

SET(CADAgent_AGENT
    agent/__init__.py
    agent/checkpoints.py
    agent/gui_thread.py
    agent/hooks.py
    agent/memory.py
    agent/permissions.py
    agent/prompts_cli.py
    agent/rewind.py
    agent/sessions.py
    agent/ui_bridge.py
)

SET(CADAgent_AGENT_CLI
    agent/cli/__init__.py
    agent/cli/doc_handle.py
    agent/cli/dock_runtime.py
    agent/cli/dock_tools.py
    agent/cli/mcp_tools.py
    agent/cli/runtime.py
    agent/cli/subagents.py
)

SET(CADAgent_AGENT_WORKER
    agent/worker/__init__.py
    agent/worker/client.py
    agent/worker/protocol.py
    agent/worker/registry.py
    agent/worker/server.py
)

SET(CADAgent_AGENT_WORKER_HANDLERS
    agent/worker/handlers/__init__.py
    agent/worker/handlers/document.py
)

SET(CADAgent_UI
    agent/ui/__init__.py
    agent/ui/qml_panel.py
)

SET(CADAgent_UI_QML
    agent/ui/qml/ChatComposer.qml
    agent/ui/qml/ChatPanel.qml
    agent/ui/qml/ChatTopBar.qml
    agent/ui/qml/HistoryPopup.qml
    agent/ui/qml/ModesPopup.qml
    agent/ui/qml/PlanBanner.qml
    agent/ui/qml/TodosPanel.qml
    agent/ui/qml/TranscriptView.qml
    agent/ui/qml/WorkspaceChip.qml
)

SET(CADAgent_UI_QML_TRANSCRIPT
    agent/ui/qml/transcript/AskRow.qml
    agent/ui/qml/transcript/AssistantRow.qml
    agent/ui/qml/transcript/CompactionRow.qml
    agent/ui/qml/transcript/DecisionRow.qml
    agent/ui/qml/transcript/EditApprovalRow.qml
    agent/ui/qml/transcript/ErrorRow.qml
    agent/ui/qml/transcript/FooterRow.qml
    agent/ui/qml/transcript/HooksStatusRow.qml
    agent/ui/qml/transcript/MessageEditOverlay.qml
    agent/ui/qml/transcript/MilestoneRow.qml
    agent/ui/qml/transcript/PermissionRow.qml
    agent/ui/qml/transcript/PlanFileRow.qml
    agent/ui/qml/transcript/RewindButton.qml
    agent/ui/qml/transcript/SubagentRow.qml
    agent/ui/qml/transcript/SystemRow.qml
    agent/ui/qml/transcript/ThinkingRow.qml
    agent/ui/qml/transcript/TodosRow.qml
    agent/ui/qml/transcript/ToolRow.qml
    agent/ui/qml/transcript/UserRow.qml
    agent/ui/qml/transcript/VerificationRow.qml
)

SET(CADAgent_SRCS
    ${CADAgent_TOP}
    ${CADAgent_AGENT}
    ${CADAgent_AGENT_CLI}
    ${CADAgent_AGENT_WORKER}
    ${CADAgent_AGENT_WORKER_HANDLERS}
    ${CADAgent_UI}
    ${CADAgent_UI_QML}
    ${CADAgent_UI_QML_TRANSCRIPT}
)

SOURCE_GROUP("" FILES ${CADAgent_SRCS})

ADD_CUSTOM_TARGET(CADAgent ALL SOURCES ${CADAgent_SRCS} ${CADAgent_QRC_SRCS})

fc_copy_sources(CADAgent "${CMAKE_BINARY_DIR}/Mod/CADAgent" ${CADAgent_SRCS})

IF (BUILD_GUI)
    fc_target_copy_resource(CADAgent
        ${CMAKE_CURRENT_BINARY_DIR}
        ${CMAKE_BINARY_DIR}/Mod/CADAgent
        CADAgent_rc.py)
ENDIF (BUILD_GUI)

INSTALL(FILES ${CADAgent_TOP} ${CADAgent_QRC_SRCS} DESTINATION Mod/CADAgent)
INSTALL(FILES ${CADAgent_AGENT} DESTINATION Mod/CADAgent/agent)
INSTALL(FILES ${CADAgent_AGENT_CLI} DESTINATION Mod/CADAgent/agent/cli)
INSTALL(FILES ${CADAgent_AGENT_WORKER} DESTINATION Mod/CADAgent/agent/worker)
INSTALL(FILES ${CADAgent_AGENT_WORKER_HANDLERS} DESTINATION Mod/CADAgent/agent/worker/handlers)
INSTALL(FILES ${CADAgent_UI} DESTINATION Mod/CADAgent/agent/ui)
INSTALL(FILES ${CADAgent_UI_QML} DESTINATION Mod/CADAgent/agent/ui/qml)
INSTALL(FILES ${CADAgent_UI_QML_TRANSCRIPT} DESTINATION Mod/CADAgent/agent/ui/qml/transcript)

# ---------------------------------------------------------------------------
# Live-LLM smoke tests (opt-in)
#
# Tests under tests/cadagent/ drive the agent end-to-end against the configured
# LiteLLM / Anthropic proxy. Each test makes real model calls, so ctest must
# not run them by default. To enable, set CADAGENT_LIVE_TESTS=1 in the env
# when invoking ctest:
#
#     CADAGENT_LIVE_TESTS=1 \
#     ANTHROPIC_BASE_URL=http://localhost:4141 \
#     ANTHROPIC_API_KEY=... \
#     ANTHROPIC_MODEL=gpt-5-mini \
#     ctest --test-dir build/debug -R CADAgent_live
#
# When the env var is unset, the wrapper prints "skipped" and returns 0 so a
# green ctest run is still green.
# ---------------------------------------------------------------------------
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(
        NAME CADAgent_live_tests
        COMMAND ${CMAKE_COMMAND} -E env
            FREECADCMD=$<TARGET_FILE_DIR:FreeCADMain>/FreeCADCmd
            ${Python3_EXECUTABLE} -c
            "import os,subprocess,sys; \
sys.exit(0) if not os.environ.get('CADAGENT_LIVE_TESTS') else \
sys.exit(subprocess.call([sys.executable,'-m','pytest','-m','live_llm','${CMAKE_SOURCE_DIR}/tests/cadagent']))"
    )
    set_tests_properties(CADAgent_live_tests PROPERTIES
        LABELS "cadagent;live_llm"
        TIMEOUT 600
    )
endif()
