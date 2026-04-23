# SPDX-License-Identifier: LGPL-2.1-or-later

IF (BUILD_GUI)
    PYSIDE_WRAP_RC(CADAgent_QRC_SRCS Resources/CADAgent.qrc)
ENDIF (BUILD_GUI)

SET(CADAgent_TOP
    Init.py
    InitGui.py
    CADAgent.py
    cli.py
    dlgPreferencesCADAgent.ui
)

SET(CADAgent_AGENT
    agent/__init__.py
    agent/runtime.py
    agent/context.py
    agent/errors.py
    agent/gui_thread.py
    agent/hooks.py
    agent/memory.py
    agent/permissions.py
    agent/prompts.py
    agent/sessions.py
    agent/ui_bridge.py
)

SET(CADAgent_UI
    agent/ui/__init__.py
    agent/ui/qml_panel.py
)

SET(CADAgent_UI_QML
    agent/ui/qml/ChatPanel.qml
)

SET(CADAgent_TOOLS
    agent/tools/__init__.py
    agent/tools/_shared.py
    agent/tools/doc.py
    agent/tools/selection.py
    agent/tools/geometry.py
    agent/tools/memory.py
    agent/tools/diagnostics.py
    agent/tools/planning.py
    agent/tools/profiles.py
)

SET(CADAgent_TOOLS_PARTDESIGN
    agent/tools/partdesign/__init__.py
    agent/tools/partdesign/_pd_shared.py
    agent/tools/partdesign/body.py
    agent/tools/partdesign/sketch.py
    agent/tools/partdesign/pad_pocket.py
    agent/tools/partdesign/dress_ups.py
)

SET(CADAgent_TOOLS_MACROS
    agent/tools/macros/__init__.py
    agent/tools/macros/_macro_shared.py
    agent/tools/macros/plate.py
    agent/tools/macros/holes.py
)

SET(CADAgent_SRCS
    ${CADAgent_TOP}
    ${CADAgent_AGENT}
    ${CADAgent_UI}
    ${CADAgent_UI_QML}
    ${CADAgent_TOOLS}
    ${CADAgent_TOOLS_PARTDESIGN}
    ${CADAgent_TOOLS_MACROS}
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
INSTALL(FILES ${CADAgent_UI} DESTINATION Mod/CADAgent/agent/ui)
INSTALL(FILES ${CADAgent_UI_QML} DESTINATION Mod/CADAgent/agent/ui/qml)
INSTALL(FILES ${CADAgent_TOOLS} DESTINATION Mod/CADAgent/agent/tools)
INSTALL(FILES ${CADAgent_TOOLS_PARTDESIGN} DESTINATION Mod/CADAgent/agent/tools/partdesign)
INSTALL(FILES ${CADAgent_TOOLS_MACROS} DESTINATION Mod/CADAgent/agent/tools/macros)

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
