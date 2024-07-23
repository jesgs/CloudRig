# SPDX-License-Identifier: GPL-2.0-or-later

from bpy.props import EnumProperty
from bpy.types import PropertyGroup
from math import radians

from .cloud_fk_chain import Component_Chain_FK


class Component_Shoulder(Component_Chain_FK):
    """A single bone control to connect an arm to a spine."""

    ui_name = "Shoulder Bone"
    forced_params = {'fk_chain.display_center': False}

    def initialize(self):
        super().initialize()
        """Gather and validate data about the rig."""
        if self.bone_count > 1:
            print(
                f"""Shoulder rig on {self.base_bone_name} has a chain of more than a single bone.
                   The rig only requires one bone, the rest will be unaffected!"""
            )

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.shoulder_setup()

    def shoulder_setup(self):
        control = self.bone_sets['FK Controls'][0]
        control.custom_shape_name = 'Clavicle'
        shoulder_rot = radians(int(self.params.shoulder.up_axis) * 90)

        control.custom_shape_rotation_euler.y = shoulder_rot

        parent = self.find_bone_info(self.base_bone_name).parent
        if parent:
            control.parent = parent

    ##############################
    # Parameters

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_appearance_params(layout, context, params)

        cls.draw_prop(context, layout, params.shoulder, 'up_axis')


class Params(PropertyGroup):
    up_axis: EnumProperty(
        name="Widget Up Axis",
        description="Rotate the bone shape to align with this axis of the bone",
        items=[
            ("0", '+Z', "Do not rotate the bone shape", 0),
            ("1", '+X', "Rotate bone shape by 90 degrees", 1),
            ("2", '-Z', "Rotate bone shape by 180 degrees", 2),
            ("3", '-X', "Rotate bone shape by -90 degrees", 3),
        ],
    )


RIG_COMPONENT_CLASS = Component_Shoulder
