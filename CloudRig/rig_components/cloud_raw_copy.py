# SPDX-License-Identifier: GPL-3.0-or-later

from .cloud_base import Component_Base


class Component_RawCopy(Component_Base):
    keep_original_bones_collections = True
    keep_original_bones_colors = True
    keep_original_bones = True

    ui_name = "Raw Copy"

    @classmethod
    def poll_draw_parenting_params(cls, context, params):
        return False

    @classmethod
    def poll_draw_control_params(cls, context, params):
        return False

    @classmethod
    def poll_draw_appearance_params(cls, context, params):
        return False

RIG_COMPONENT_CLASS = Component_RawCopy
