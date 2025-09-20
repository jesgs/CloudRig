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

    def create_bone_infos(self, context):
        super().create_bone_infos(context)

        sphere_bone_name = self.params.chain_sphere.sphere_bone
        sphere_bone = self.get_metarig_pbone(sphere_bone_name)
        if not sphere_bone:
            self.raise_generation_error("Sphere Bone not found", trouble_bone=sphere_bone_name)
            return

        for main_str in self.main_str_bones:
            rot_ctrl = self.bone_sets['Sphere Controls'].new(
                source=main_str,
                parent=main_str.parent,
                name=main_str.name.replace("STR-", "SPH-"),

                head=sphere_bone.head.copy(),
                tail=main_str.head.copy(),

                custom_shape_name='Square',
                custom_shape_along_length=1.0,
                display_type='WIRE',

                roll=0,
                roll_type='VECTOR',
                roll_vector=main_str.tail,
                rotation_mode='YZX',
            )
            main_str.parent = rot_ctrl
            if self.params.chain.smooth_spline:
                main_str.add_constraint('COPY_ROTATION',
                    mix_mode='BEFORE',
                    target_space='LOCAL_OWNER_ORIENT',
                    owner_space='LOCAL',
                    subtarget=rot_ctrl,
                )

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
