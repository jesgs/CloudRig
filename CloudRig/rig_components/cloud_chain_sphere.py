# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.props import StringProperty, PointerProperty
from bpy.types import PropertyGroup, Object

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.bone_set import BoneSet
from .cloud_chain import Component_ToonChain


class Component_SphereChain(Component_ToonChain):
    """Stretchy chain for spherical deformation. Useful for gigantic eyelids."""

    ui_name = "Chain: Sphere"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def toon__make_main_str_bone(self, org_bone: BoneInfo, at_tip=False) -> BoneInfo:
        str_bone = super().toon__make_main_str_bone(org_bone, at_tip)

        sphere_bone_name = self.params.chain_sphere.sphere_bone
        sphere_bone = self.get_metarig_pbone(sphere_bone_name)
        if not sphere_bone:
            self.raise_generation_error("Sphere Bone not found", trouble_bone=sphere_bone_name)
            return str_bone

        parent_helper = str_bone.parent_helper
        rot_ctrl = self.bone_sets['Sphere Controls'].new(
            source=str_bone,
            parent=parent_helper.constraint_infos[0]['subtarget'],
            name=str_bone.name.replace("STR-", "SPH-"),

            head=sphere_bone.head.copy(),
            tail=str_bone.head.copy(),

            custom_shape_name='Square',
            custom_shape_along_length=1.0,
            display_type='WIRE',

            roll=0,
            roll_type='VECTOR',
            roll_vector=str_bone.tail,
            rotation_mode='YZX',
        )

        parent_helper.constraint_infos[0]['subtarget'] = rot_ctrl

        return str_bone

    ##############################
    # Parameters

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        # We only want to draw this bone set UI if the option for it is enabled.
        if set_name in ["deform_controls", "deform_helpers"]:
            return params.chain.unlock_deform
        if set_name == 'shape_key_helpers':
            return params.chain.shape_key_helpers
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Sphere Controls', color_palette='THEME09', wire_width=1.5)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        super().draw_control_params(layout, context, params)
        cls.draw_prop_search(
            context,
            layout.row(),
            params.chain_sphere,
            "sphere_bone",
            context.active_object.data,
            "bones",
        )
        cls.draw_prop(context, layout, params.chain_sphere, 'shrinkwrap_mesh')


class Params(PropertyGroup):
    sphere_bone: StringProperty(
        name="Sphere Bone",
        description="Bone to use as the center of the sphere.",
        default="",
    )
    shrinkwrap_mesh: PointerProperty(
        type=Object,
        name="Shrinkwrap Mesh",
        description="Mesh object to shrinkwrap to using Shrinkwrap Constraints.",
    )

RIG_COMPONENT_CLASS = Component_SphereChain
