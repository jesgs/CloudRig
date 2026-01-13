# SPDX-License-Identifier: GPL-3.0-or-later

from .cloud_base import Component_Base


class Component_RawCopy(Component_Base):
    # For Raw Copy,
    keep_original_bones_collections = True
    keep_original_bones_colors = True

    ui_name = "Raw Copy"

RIG_COMPONENT_CLASS = Component_RawCopy
