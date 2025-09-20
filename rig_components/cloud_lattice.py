# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import PropertyGroup, PoseBone, Object
from ..rig_component_features.bone_info import BoneInfo, ConstraintInfo
from bpy.props import BoolProperty, PointerProperty
from mathutils import Matrix

from ..utils.lattice import ensure_falloff_vgroup
from .cloud_base import Component_Base


class Component_Lattice(Component_Base):
    """Create a simple lattice set-up. Lattice modifiers have to be added manually to the objects that should be deformed."""

    ui_name = "Lattice"

    relink_default_prefix = "LTC"

    keep_original_bones = False

    def initialize(self):
        super().initialize()
        self.create_deform_bone = False

    def create_bone_infos(self, context):
        super().create_bone_infos(context)
        self.test_lattice_already_used()
        self.lattice_root = self.make_lattice_root_ctrl(self.root_bone)
        self.hook_bone = self.make_hook_ctrl(self.lattice_root)

    def make_lattice_root_ctrl(self, org_bi):
        name_parts = self.naming.slice_name(org_bi)
        root_name = self.naming.make_name(['ROOT', 'LTC'], name_parts[1], name_parts[2])
        root_bone = self.bone_sets['Lattice Controls'].new(
            name=root_name,
            source=org_bi,
            parent=org_bi.parent,
        )
        if org_bi.custom_shape:
            root_bone.copy_custom_shape(org_bi)
        else:
            root_bone.custom_shape_name="Cube"
            root_bone.use_custom_shape_bone_size=True
        return root_bone

    def make_hook_ctrl(self, root_bone):
        hook_name = root_bone.name.replace("ROOT-LTC", "LTC")
        hook_bone = self.bone_sets['Lattice Controls'].new(
            name=hook_name,
            source=root_bone,
            parent=root_bone,
            custom_shape_name="Sphere",
            use_custom_shape_bone_size=True,
        )
        return hook_bone

    def create_helper_objects(self, context):
        super().create_helper_objects(context)
        root_pb = self.target_rig.pose.bones.get(self.lattice_root.name)
        hook_pb = self.target_rig.pose.bones.get(self.hook_bone.name)
        lattice_ob = self.params.lattice.lattice = self.ensure_lattice(context, hook_pb.name)
        if self.params.lattice.regenerate:
            self.reset_lattice(context, self.params.lattice.lattice, root_pb, hook_pb)
        else:
            # Reset Hook inverse matrices
            for m in lattice_ob.modifiers:
                if m.type == 'HOOK':
                    m.subtarget = m.subtarget

    def ensure_lattice(self, context, lattice_name="Lattice") -> Object:
        lattice_ob = self.params.lattice.lattice
        if lattice_ob:
            return lattice_ob

        lattice = bpy.data.lattices.new(lattice_name)
        lattice_ob = bpy.data.objects.new(lattice_name, lattice)
        context.scene.collection.objects.link(lattice_ob)
        return lattice_ob

    def reset_lattice(
        self, context, lattice_ob: Object, root_bone: PoseBone, hook_bone: PoseBone
    ):
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

        # Parent lattice to the generated rig
        lattice_ob.parent = self.target_rig
        # Bone-parent lattice to root bone
        lattice_ob.parent_type = 'BONE'
        lattice_ob.parent_bone = self.lattice_root.name
        lattice_ob.matrix_world = root_bone.matrix
        lattice_ob.matrix_world = lattice_ob.matrix_world @ Matrix.Scale(
            root_bone.length, 4
        )
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

    def test_lattice_already_used(self) -> bool:
        """Test if the target lattice object is already being used by
        another cloud_lattice rig."""

        for bone_name, component in self.generator.component_map.items():
            if isinstance(component, type(self)):
                if component == self:
                    return
                if (
                    component.params.lattice.lattice == self.params.lattice.lattice
                    and self.params.lattice.lattice != None
                ):
                    self.raise_generation_error(
                        "Lattice shared by multiple components",
                        operator='object.cloudrig_clear_pointer_param',
                        op_kwargs={
                            'bone_name': self.metarig_base_pbone.name,
                            'param_name': 'lattice.lattice',
                        },
                    )

    ##############################
    # Parameters

    @classmethod
    def define_bone_sets(cls):
        """Create parameters for this rig's bone sets."""
        super().define_bone_sets()
        cls.define_bone_set('Lattice Controls', color_palette='THEME12')

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        if set_name == 'deform_bones':
            return False
        return super().is_bone_set_used(context, rig, params, set_name)

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""
        cls.draw_prop(context, layout, params.lattice, "lattice")
        cls.draw_prop(context, layout, params.lattice, "regenerate")


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


RIG_COMPONENT_CLASS = Component_Lattice
