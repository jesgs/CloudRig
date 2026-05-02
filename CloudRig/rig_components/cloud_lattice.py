# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty, PointerProperty
from bpy.types import Object, PropertyGroup
from mathutils import Matrix

from ..rig_component_features.bone_info import BoneInfo
from ..utils.lattice import ensure_falloff_vgroup
from .cloud_base import Component_Base


class Component_Lattice(Component_Base):
    """Create a simple lattice setup. Lattice modifiers have to be added manually to the objects that should be deformed."""

    ui_name = "Lattice"

    relink_default_prefix = "LTC"

    keep_original_bones = False

    max_bones_in_chain = 1

    ##############################
    # Inherited functions.

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.__check_lattice_already_used()
        self.root_bone = self.lattice_root = self.__make_lattice_root(self.root_bone)
        self.hook_bone = self.__make_hook_ctrl(self.lattice_root)

    def create_helper_objects(self, context):
        super().create_helper_objects(context)
        lattice_ob = self.params.lattice.lattice = self.__ensure_lattice(context, self.hook_bone.name)
        if self.params.lattice.regenerate:
            self.__reset_lattice(context, lattice_ob, self.lattice_root, self.hook_bone)
        else:
            # Reset Hook inverse matrices
            for m in lattice_ob.modifiers:
                if m.type == 'HOOK':
                    m.subtarget = m.subtarget
        self.check_object_in_scene(context, lattice_ob)

    ##############################
    # Lattice functions.

    def __check_lattice_already_used(self):
        """Test if the target lattice object is already being used by
        another cloud_lattice rig."""

        for bone_name, component in self.generator.component_map.items():
            if isinstance(component, type(self)):
                if component == self:
                    return
                if (
                    component.params.lattice.lattice == self.params.lattice.lattice
                    and self.params.lattice.lattice is not None
                ):
                    self.raise_generation_error(
                        rpt_("Lattice shared by multiple components"),
                        operator='object.cloudrig_clear_pointer_param',
                        op_kwargs={
                            'bone_name': self.metarig_base_pbone.name,
                            'param_name': 'lattice.lattice',
                        },
                    )

    def __make_lattice_root(self, org_bi: BoneInfo) -> BoneInfo:
        root_bone = self.bone_sets['Lattice Controls'].new(
            name=self.naming.add_prefix(org_bi, "ROOT-LTC"),
            source=org_bi,
            parent=org_bi.parent,
        )
        if org_bi.custom_shape:
            root_bone.copy_custom_shape(org_bi)
        else:
            root_bone.custom_shape_name=self.params.lattice.shape_root.shape_name
            root_bone.use_custom_shape_bone_size=True
        return root_bone

    def __make_hook_ctrl(self, root_bone: BoneInfo) -> BoneInfo:
        hook_bone = self.bone_sets['Lattice Controls'].new(
            name=self.naming.add_prefix(root_bone.source, "LTC"),
            source=root_bone,
            parent=root_bone,
            custom_shape_name=self.params.lattice.shape_lattice.shape_name,
            use_custom_shape_bone_size=True,
        )
        return hook_bone

    def __ensure_lattice(self, context, lattice_name="Lattice") -> Object:
        lattice_ob = self.params.lattice.lattice
        if lattice_ob:
            return lattice_ob

        lattice = bpy.data.lattices.new(lattice_name)
        lattice_ob = bpy.data.objects.new(lattice_name, lattice)
        context.scene.collection.objects.link(lattice_ob)
        return lattice_ob

    def __reset_lattice(
        self,
        context,
        lattice_ob: Object,
        root_bone: BoneInfo,
        hook_bone: BoneInfo,
    ) -> Object:
        # If lattice doesn't exist, create it.
        if not lattice_ob:
            lattice_name = hook_bone.name
            lattice = bpy.data.lattices.new(lattice_name)
            lattice_ob = bpy.data.objects.new(lattice_name, lattice)
            context.scene.collection.objects.link(lattice_ob)
        else:
            lattice_ob.modifiers.clear()
            lattice_ob.constraints.clear()

        resolution = 10
        # Set resolution
        lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = (
            1,
            1,
            1,
        )
        lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = [
            resolution
        ] * 3

        # Create a falloff vertex group
        vg = ensure_falloff_vgroup(lattice_ob, vg_name="Hook", multiplier=1.5)

        # Parent lattice to the Target Rig
        lattice_ob.parent = self.target_rig
        # Bone-parent lattice to root bone
        lattice_ob.parent_type = 'BONE'
        lattice_ob.parent_bone = self.lattice_root.name
        lattice_ob.matrix_world = root_bone.matrix
        scale = sum((abs(s) for s in root_bone.custom_shape_scale_xyz))/3
        if root_bone.use_custom_shape_bone_size:
            scale *= root_bone.length
        lattice_ob.matrix_world = lattice_ob.matrix_world @ Matrix.Scale(scale, 4)
        # Leave a custom property for the Generator, so it doesn't reset the
        # lattice's matrix to what it was before generation.
        lattice_ob['matrix_world'] = lattice_ob.matrix_world

        self.lock_transforms(lattice_ob)

        # Add Hook modifier to the lattice
        hook_mod = lattice_ob.modifiers.new(name="Hook", type='HOOK')
        hook_mod.object = self.target_rig
        hook_mod.vertex_group = vg.name
        hook_mod.subtarget = hook_bone.name

        return lattice_ob

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set(n_("Lattice Controls"), color_palette='THEME12', wire_width=2.0)

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'deform_bones':
            return False
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_control_params(cls, layout, context, component):
        params = component.params
        cls.draw_prop(context, layout, params.lattice, "lattice")
        cls.draw_prop(context, layout, params.lattice, "regenerate")

    @classmethod
    def draw_appearance_params(cls, layout, context, component):
        super().draw_appearance_params(layout, context, component)
        params = component.params
        cls.draw_prop_custom_shape(context, layout, params.lattice, 'shape_root')
        cls.draw_prop_custom_shape(context, layout, params.lattice, 'shape_lattice')

class Params(PropertyGroup):
    lattice: PointerProperty(
        type=Object,
        name="Lattice",
        description="Lattice Object that will be hooked up to this control. If not left empty, the already existing lattice will not be affected in any way, unless Regenerate Lattice is enabled",
    )
    regenerate: BoolProperty(
        name="Regenerate",
        description="Whether to re-generate the lattice object on rig generation. Disable if you intend to modify the generated lattice object manually",
        default=True,
    )

    shape_root: Component_Base.make_custom_shape_params(
        identifier="Lattice Root",
        default="Cube"
    )
    shape_lattice: Component_Base.make_custom_shape_params(
        identifier="Lattice Control",
        default="Sphere"
    )


RIG_COMPONENT_CLASS = Component_Lattice
