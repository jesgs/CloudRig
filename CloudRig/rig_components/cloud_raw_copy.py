# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from bpy.types import Context

from .cloud_base import Component_Base


class Component_RawCopy(Component_Base):
    """Copy a bone to the target rig exactly as-is, preserving its collections, colors, and deform settings."""

    keep_original_bones_collections = True
    keep_original_bones_colors = True
    keep_original_bones = True
    max_bones_in_chain = 1

    ui_name = "Raw Copy"

    def create_bone_infos(self, context: Context):
        """Copy the metarig bone's deform setting to the ORG bone."""
        super().create_bone_infos(context)
        metarig_pbone = self.get_metarig_pbone(self.bones_org[0].name)
        self.bones_org[0].use_deform = metarig_pbone.bone.use_deform

    ### Disable inherited functionalities.

    def base__apply_custom_root_parent(self, **kwargs):
        """No-op: raw copies skip custom root parenting."""
        return

    def base__apply_parent_switching(self, **kwargs):
        """No-op: raw copies don't support parent switching."""
        return

    @classmethod
    def poll_draw_parenting_params(cls, **kwargs):
        """Hide the parenting parameters panel for raw copies."""
        return False

    @classmethod
    def poll_draw_control_params(cls, **kwargs):
        """Hide the control parameters panel for raw copies."""
        return False

    @classmethod
    def poll_draw_appearance_params(cls, **kwargs):
        """Hide the appearance parameters panel for raw copies."""
        return False


RIG_COMPONENT_CLASS = Component_RawCopy
