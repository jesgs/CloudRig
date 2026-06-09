# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import ComponentParams, RigComponent

from bpy.types import Context, Object, PropertyGroup, UILayout

from .cloud_fk_chain import Component_Chain_FK


class Component_Feather(Component_Chain_FK):
    """Single-bone rig for a simple feather."""

    ui_name = "Feather"
    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.display_center': False,
    }

    max_bones_in_chain = 1

    def create_bone_infos(self, context: Context):
        """Build the feather FK control, a bend control at the base, and a visual line helper."""
        super().create_bone_infos(context)

        first_fk = self.bone_sets['FK Controls'][0]
        feather_shape = self.params.feather.shape_feather.shape_name
        first_fk.custom_shape_name = feather_shape
        first_fk.custom_shape_along_length = 1.0

        # Create a new bone parented to ORG, and parent the tip control to it.
        org_bone = self.bones_org[0]
        bend_ctr = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org_bone, "BEND"),
            source=org_bone,
            parent=org_bone,
            custom_shape_name=feather_shape,
        )
        self.main_str_bones[-1].parent = bend_ctr
        bend_ctr.custom_shape_along_length = 0.95

        # Create a visual helper line from the bend to the FK control's display positions.
        line = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org_bone, "LINE"),
            source=bend_ctr,
            parent=bend_ctr,
            head=bend_ctr.head + bend_ctr.vector * 0.95,
            tail=bend_ctr.tail,
            custom_shape_name="Line",
            use_custom_shape_bone_size=True,
        )
        bend_ctr.collections = line.collections = self.bone_sets['Stretch Controls'].collections
        line.bbone_width *= 0.2
        line.hide_select = True

        line.add_constraint('STRETCH_TO', subtarget=first_fk.name, head_tail=1)

        # Make the tip control copy partial rotation of the bend control
        self.main_str_bones[-1].add_constraint('COPY_ROTATION', subtarget=bend_ctr.name, influence=0.4)

    @classmethod
    def is_bone_set_used(cls, context: Context, rig: Object, params: ComponentParams, set_name: str) -> bool:
        if set_name == 'fk_controls_extra':
            return True

        return super().is_bone_set_used(context, rig, params, set_name)

    ##############################
    # Parameters

    @classmethod
    def draw_appearance_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        cls.draw_prop_custom_shape(context, layout, params.feather, 'shape_feather')


class Params(PropertyGroup):
    shape_feather: Component_Chain_FK.make_custom_shape_params(identifier="Feather", default="Feather")


RIG_COMPONENT_CLASS = Component_Feather
