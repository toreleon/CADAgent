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

#include "PreCompiled.h"

#ifndef _PreComp_
#include <QLabel>
#include <QVBoxLayout>
#endif

#include "CADAgentView.h"


using namespace Gui;

CADAgentView::CADAgentView(QWidget* parent)
    : QWidget(parent)
    , m_layout(new QVBoxLayout(this))
    , m_content(nullptr)
{
    m_layout->setContentsMargins(0, 0, 0, 0);
    m_layout->setSpacing(0);

    // Placeholder shown until the CADAgent Mod attaches its QML panel.
    auto placeholder = new QLabel(tr("Loading CAD Agent…"), this);
    placeholder->setAlignment(Qt::AlignCenter);
    m_layout->addWidget(placeholder);
    m_content = placeholder;
}

CADAgentView::~CADAgentView() = default;

void CADAgentView::setContentWidget(QWidget* widget)
{
    if (widget == m_content) {
        return;
    }
    if (m_content) {
        m_layout->removeWidget(m_content);
        m_content->deleteLater();
        m_content = nullptr;
    }
    if (widget) {
        widget->setParent(this);
        m_layout->addWidget(widget);
        m_content = widget;
    }
}

QWidget* CADAgentView::contentWidget() const
{
    return m_content;
}

#include "moc_CADAgentView.cpp"
