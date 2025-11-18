# SPDX-License-Identifier: GPL-3.0-or-later

from .cloud_fk_chain import Component_Chain_FK
from bpy.types import PropertyGroup

class Component_Feather(Component_Chain_FK):
    """Single-bone rig for a simple feather."""

    ui_name = "Feather"
    forced_params = {
        'chain.segments': 1,
        'chain.tip_control': True,
        'fk_chain.display_center': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.bone_count != 1:
            self.raise_generation_error("Feather rig must consist of exactly 1 bone.")

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        first_fk = self.bone_sets['FK Controls'][0]
        feather_shape = self.params.feather.shape_feather
        first_fk.custom_shape_name = feather_shape
        first_fk.custom_shape_along_length = 1

        # Create a new bone parented to ORG, and parent the tip control to it.
        org = self.bones_org[0]
        bend_ctr = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org.name, "BEND"),
            source=org,
            parent=org,
            custom_shape_name=feather_shape,
        )
        self.main_str_bones[-1].parent = bend_ctr
        bend_ctr.custom_shape_along_length = 0.95

        # Create a visual helper line from the bend to the FK control's display positions.
        line = self.bone_sets['FK Controls Extra'].new(
            name=self.naming.add_prefix(org.name, "LINE-BEND"),
            source=bend_ctr,
            parent=bend_ctr,
            head=bend_ctr.head + bend_ctr.vector * 0.95,
            tail=bend_ctr.tail,
            custom_shape_name="Line",
            use_custom_shape_bone_size=True,
        )
        bend_ctr.collections = line.collections = self.bone_sets[
            'Stretch Controls'
        ].collections
        line.bbone_width *= 0.2
        line.hide_select = True

        line.add_constraint('STRETCH_TO', subtarget=first_fk.name, head_tail=1)

        # Make the tip control copy partial rotation of the bend control
        self.main_str_bones[-1].add_constraint(
            'COPY_ROTATION', subtarget=bend_ctr.name, influence=0.4
        )

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'fk_controls_extra':
            return True

        return super().is_bone_set_used(context, rig, params, set_name)

    ##############################
    # Parameters

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        super().draw_appearance_params(layout, context, params)
        cls.draw_prop_custom_shape(context, layout, params.feather, 'shape_feather')

class Params(PropertyGroup):
    shape_feather: Component_Chain_FK.make_custom_shape_params(
        identifier="Feather",
        default="Feather"
    )

RIG_COMPONENT_CLASS = Component_Feather
