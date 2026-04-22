# SPDX-License-Identifier: LGPL-2.1-or-later

IF (BUILD_GUI)
    PYSIDE_WRAP_RC(CADAgent_QRC_SRCS Resources/CADAgent.qrc)
ENDIF (BUILD_GUI)

SET(CADAgent_TOP
    Init.py
    InitGui.py
    CADAgent.py
    dlgPreferencesCADAgent.ui
)

SET(CADAgent_AGENT
    agent/__init__.py
    agent/runtime.py
    agent/bridge.py
    agent/context.py
    agent/errors.py
    agent/gui_thread.py
    agent/memory.py
    agent/permissions.py
    agent/prompts.py
    agent/sessions.py
)

SET(CADAgent_UI
    agent/ui/__init__.py
    agent/ui/panel.py
    agent/ui/web_panel.py
    agent/ui/widgets.py
    agent/ui/composer.py
    agent/ui/history_popup.py
    agent/ui/styles.py
)

SET(CADAgent_TOOLS
    agent/tools/__init__.py
    agent/tools/_shared.py
    agent/tools/doc.py
    agent/tools/selection.py
    agent/tools/geometry.py
    agent/tools/memory.py
    agent/tools/diagnostics.py
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

SET(CADAgent_WEB
    Resources/web/index.html
    Resources/web/README.md
)

SET(CADAgent_SRCS
    ${CADAgent_TOP}
    ${CADAgent_AGENT}
    ${CADAgent_UI}
    ${CADAgent_TOOLS}
    ${CADAgent_TOOLS_PARTDESIGN}
    ${CADAgent_TOOLS_MACROS}
    ${CADAgent_WEB}
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
INSTALL(FILES ${CADAgent_TOOLS} DESTINATION Mod/CADAgent/agent/tools)
INSTALL(FILES ${CADAgent_TOOLS_PARTDESIGN} DESTINATION Mod/CADAgent/agent/tools/partdesign)
INSTALL(FILES ${CADAgent_TOOLS_MACROS} DESTINATION Mod/CADAgent/agent/tools/macros)
INSTALL(FILES ${CADAgent_WEB} DESTINATION Mod/CADAgent/Resources/web)
