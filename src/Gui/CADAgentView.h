/***************************************************************************
 *   Copyright (c) 2026 FreeCAD Project Association <www.freecad.org>      *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#pragma once

#include <QWidget>
#include <FCGlobal.h>

class QVBoxLayout;

namespace Gui
{

/** Host dock for the CAD Agent chat panel.
 *
 * The widget lives in core Gui so it can be registered with
 * Gui::DockWindowManager during MainWindow construction, just like
 * Std_ReportView and Std_PythonView. It is a thin shell — the actual chat UI
 * (a QML panel + Claude Agent SDK runtime) is loaded by the CADAgent Mod and
 * reparented in via setContentWidget().
 */
class GuiExport CADAgentView: public QWidget
{
    Q_OBJECT

public:
    explicit CADAgentView(QWidget* parent = nullptr);
    ~CADAgentView() override;

    /** Reparent \a widget into this host, replacing any prior content.
     *  Called from PySide once the CADAgent Mod has constructed its
     *  QmlChatPanel.
     */
    Q_INVOKABLE void setContentWidget(QWidget* widget);

    /** Returns the currently embedded content, or nullptr if none. */
    Q_INVOKABLE QWidget* contentWidget() const;

private:
    QVBoxLayout* m_layout;
    QWidget* m_content;
};

}  // namespace Gui
