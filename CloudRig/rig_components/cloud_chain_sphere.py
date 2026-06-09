# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import ComponentParams, RigComponent

from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import PointerProperty, StringProperty
from bpy.types import Context, Object, PropertyGroup, UILayout

from ..rig_component_features.bone_info import BoneInfo
from .cloud_chain import Component_ToonChain


class Component_SphereChain(Component_ToonChain):
    """Stretchy chain for spherical deformation. Useful for gigantic eyelids."""

    ui_name = "Chain: Sphere"

    ##############################
    # Inherited functions.

    def toon__make_main_str_bone(self, org_bone: BoneInfo, at_tip=False) -> BoneInfo:
        """Extend the parent implementation by adding a sphere control to each stretch bone."""
        str_bone = super().toon__make_main_str_bone(org_bone, at_tip)
        self.__make_sphere_control(str_bone)
        return str_bone

    ##############################
    # Sphere Chain functions.

    def __make_sphere_control(self, str_bone: BoneInfo) -> BoneInfo:
        sphere_bone_name = self.params.chain_sphere.sphere_bone
        sphere_ctrl = self.get_metarig_pbone(sphere_bone_name)
        if not sphere_ctrl:
            self.raise_generation_error(
                rpt_("Sphere Bone not found"),
                trouble_bone=sphere_bone_name,
            )

        sph_ctrl = self.bone_sets['Sphere Controls'].new(
            source=str_bone,
            parent=str_bone.source,
            name=str_bone.name.replace("STR-", "SPH-"),
            head=sphere_ctrl.head.copy(),
            tail=str_bone.head.copy(),
            custom_shape_name=self.params.chain_sphere.shape_sphere_control.shape_name,
            custom_shape_along_length=1.0,
            use_custom_shape_bone_size=False,
            display_type='WIRE',
            rotation_mode='YZX',
        )
        sph_ctrl.roll_align_vector(str_bone.tail)

        arm_con = str_bone.parent_armature_constraint
        if arm_con:
            arm_con.targets = [sph_ctrl.name]

        return sph_ctrl

    ##############################
    # Parameters

    @classmethod
    def is_bone_set_used(cls, context: Context, rig: Object, params: ComponentParams, set_name: str) -> bool:
        """Return whether the named bone set is used given the current params."""
        if set_name in ["deform_controls", "deform_helpers"]:
            return params.chain.unlock_deform
        if set_name == 'shape_key_helpers':
            return params.chain.shape_key_helpers
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_appearance_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        cls.draw_prop_custom_shape(context, layout, params.chain_sphere, 'shape_sphere_control')

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(
            n_("Sphere Controls"),
            color_palette='THEME09',
        )

    @classmethod
    def draw_control_params(cls, layout: UILayout, context: Context, component: RigComponent):
        super().draw_control_params(layout, context, component)
        params = component.params
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

    shape_sphere_control: Component_ToonChain.make_custom_shape_params(identifier="Sphere Control", default="Square")


RIG_COMPONENT_CLASS = Component_SphereChain
