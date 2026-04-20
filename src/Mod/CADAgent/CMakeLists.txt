# SPDX-License-Identifier: LGPL-2.1-or-later

IF (BUILD_GUI)
    PYSIDE_WRAP_RC(CADAgent_QRC_SRCS Resources/CADAgent.qrc)
ENDIF (BUILD_GUI)

SET(CADAgent_SRCS
    Init.py
    InitGui.py
    CADAgent.py
    ChatPanel.py
    WebChatPanel.py
    Bridge.py
    AgentRuntime.py
    tools.py
    tools_partdesign.py
    tools_macros.py
    tools_diagnostics.py
    profiles.py
    errors.py
    permissions.py
    prompts.py
    gui_thread.py
    project_memory.py
    context.py
    dlgPreferencesCADAgent.ui
    Resources/web/index.html
    Resources/web/README.md
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

INSTALL(FILES ${CADAgent_SRCS} ${CADAgent_QRC_SRCS} DESTINATION Mod/CADAgent)
