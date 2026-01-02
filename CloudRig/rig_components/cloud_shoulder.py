# SPDX-License-Identifier: GPL-3.0-or-later

from math import radians

from bpy.props import EnumProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from .cloud_fk_chain import Component_Chain_FK


class Component_Shoulder(Component_Chain_FK):
    """A single bone control to connect an arm to a spine."""

    ui_name = "Shoulder Bone"
    forced_params = {
        'fk_chain.display_center': False,
        'fk_chain.create_curl_control': False,
        'fk_chain.counter_rotate_stretch_bones': 0.0,
        'fk_chain.double_first': False,
        'chain.segments': 1,
    }

    max_bones_in_chain = 1

    ##############################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.bone_count > 1:
            print(
                f"""Shoulder rig on {self.base_bone_name} has a chain of more than a single bone.
                   The rig only requires one bone, the rest will be unaffected!"""
            )

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.__make_shoulder()

    ##############################
    # Shoulder functions.

    def __make_shoulder(self):
        shoulder = self.bone_sets['FK Controls'][0]
        shoulder.custom_shape_name = self.params.shoulder.shape_shoulder.shape_name
        up_axis = self.params.shoulder.up_axis
        shoulder_rot = radians(int(up_axis) * 90)

        shoulder.custom_shape_rotation_euler.y = shoulder_rot
        offsets = {
            '0': Vector((0, 1, 1)),
            '1': Vector((1, 1, 0)),
            '2': Vector((0, 1, -1)),
            '3': Vector((-1, 1, 0)),
        }

        shoulder.custom_shape_translation += offsets[up_axis] * shoulder.length

        parent = self.find_bone_info(self.base_bone_name).parent
        if parent:
            shoulder.parent = parent

    ##############################
    # Parameters

    @classmethod
    def draw_appearance_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        super().draw_appearance_params(layout, context, params)

        cls.draw_prop(context, layout, params.shoulder, 'up_axis')


class Params(PropertyGroup):
    shape_shoulder: Component_Shoulder.make_custom_shape_params(
        identifier="Shoulder",
        default="Shoulder"
    )

    up_axis: EnumProperty(
        name="Custom Shape Up Axis",
        description="Rotate the bone shape to align with this axis of the bone",
        items=[
            ("0", '+Z', "Do not rotate the bone shape", 0),
            ("1", '+X', "Rotate bone shape by 90 degrees", 1),
            ("2", '-Z', "Rotate bone shape by 180 degrees", 2),
            ("3", '-X', "Rotate bone shape by -90 degrees", 3),
        ],
    )


RIG_COMPONENT_CLASS = Component_Shoulder
