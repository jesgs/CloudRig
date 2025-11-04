# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.types import PropertyGroup
from bpy.props import BoolProperty

from ..rig_component_features.bone_info import BoneInfo
from .cloud_base import Component_Base


class Component_TweakBone(Component_Base):
    """Tweak a single bone with the same name as this bone in the generated rig."""

    ui_name = "Bone Tweak"
    parent_switch_behaviour = "The active parent will own the tweaked bone."

    keep_original_bones = False
    keep_original_bones_collections = True
    keep_original_bones_colors = True

    ################################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tweak_bone = None

    def base__load_metarig_bones(self) -> dict[str, BoneInfo]:
        bone_infos = super().base__load_metarig_bones()
        assert len(bone_infos) == 1

        bone_info_tuple = [(key, value) for key, value in bone_infos.items()][0]
        self.original_name, self_bone = bone_info_tuple
        self_bone.name += "_Tweak"
        return bone_infos

    def create_component_interactions(self, context):
        org_bi = self.bones_org[0]
        self.tweak_bone = tweak_bone = self.generator.find_bone_info(self.original_name)

        if not self.tweak_bone:
            self.add_log(
                "No bone to tweak",
                description=f'Could not find a bone called "{self.original_name}" on the generated rig. If it exists, ensure this Tweak component is generated AFTER the component you want to tweak.',
                operator='object.cloudrig_rename_bone',
                op_kwargs={'old_name': self.original_name},
            )
            return

        self.root_bone = self.tweak_bone  # Allow parenting parameters to work

        if self.params.tweak.transforms:
            tweak_bone.head = org_bi.head.copy()
            tweak_bone.tail = org_bi.tail.copy()
            tweak_bone.roll = org_bi.roll
            tweak_bone.roll_type = ""
            tweak_bone.bbone_x = org_bi.bbone_x
            tweak_bone.bbone_z = org_bi.bbone_z

        if self.params.tweak.locks:
            tweak_bone.lock_location = org_bi.lock_location[:]
            tweak_bone.lock_rotation = org_bi.lock_rotation[:]
            tweak_bone.lock_rotation_w = org_bi.lock_rotation_w
            tweak_bone.lock_scale = org_bi.lock_scale[:]

        if self.params.tweak.rot_mode:
            tweak_bone.rotation_mode = org_bi.rotation_mode

        if self.params.tweak.shape:
            tweak_bone.custom_shape = org_bi.custom_shape
            tweak_bone.custom_shape_wire_width = org_bi.custom_shape_wire_width
            tweak_bone.custom_shape_name = org_bi.custom_shape_name
            tweak_bone.custom_shape_scale_xyz = org_bi.custom_shape_scale_xyz
            if tweak_bone.use_custom_shape_bone_size:
                scalar = tweak_bone.length / org_bi.length
                tweak_bone.custom_shape_scale_xyz = (
                    org_bi.custom_shape_scale_xyz * scalar
                )
            if not org_bi.use_custom_shape_bone_size:
                tweak_bone.custom_shape_scale_xyz /= (
                    tweak_bone.bbone_width * 10 * self.scale
                )
            tweak_bone.custom_shape_transform = org_bi.custom_shape_transform
            tweak_bone.use_custom_shape_bone_size = org_bi.use_custom_shape_bone_size
            tweak_bone.show_wire = org_bi.show_wire
            tweak_bone.custom_shape_translation = org_bi.custom_shape_translation
            tweak_bone.custom_shape_rotation_euler = org_bi.custom_shape_rotation_euler
            if org_bi.custom_shape:
                self.add_to_widget_collection(context, org_bi.custom_shape)

        if self.params.tweak.collections:
            tweak_bone.collections = org_bi.collections
        if self.params.tweak.color_palette:
            tweak_bone.color_palette_base = org_bi.color_palette_base
            tweak_bone.color_palette_pose = org_bi.color_palette_pose

        if self.params.tweak.ik_settings:
            tweak_bone.ik_stretch = org_bi.ik_stretch
            tweak_bone.lock_ik_x = org_bi.lock_ik_x
            tweak_bone.lock_ik_y = org_bi.lock_ik_y
            tweak_bone.lock_ik_z = org_bi.lock_ik_z
            tweak_bone.ik_stiffness_x = org_bi.ik_stiffness_x
            tweak_bone.ik_stiffness_y = org_bi.ik_stiffness_y
            tweak_bone.ik_stiffness_z = org_bi.ik_stiffness_z
            tweak_bone.use_ik_limit_x = org_bi.use_ik_limit_x
            tweak_bone.use_ik_limit_y = org_bi.use_ik_limit_y
            tweak_bone.use_ik_limit_z = org_bi.use_ik_limit_z
            tweak_bone.ik_min_x = org_bi.ik_min_x
            tweak_bone.ik_max_x = org_bi.ik_max_x
            tweak_bone.ik_min_y = org_bi.ik_min_y
            tweak_bone.ik_max_y = org_bi.ik_max_y
            tweak_bone.ik_min_z = org_bi.ik_min_z
            tweak_bone.ik_max_z = org_bi.ik_max_z

        if self.params.tweak.bbone_props:
            tweak_bone.bbone_segments = org_bi.bbone_segments
            tweak_bone.bbone_x = org_bi.bbone_x
            tweak_bone.bbone_z = org_bi.bbone_z

        if self.params.tweak.custom_props:
            for prop_name in org_bi.custom_props:
                tweak_bone.custom_props[prop_name] = org_bi.custom_props[prop_name]

        super().create_component_interactions(context)

        if self.params.tweak.ensure_free and len(tweak_bone.constraint_infos) > 0:
            self.root_bone = self.create_parent_constraint_holder(tweak_bone, bone_set=self.bone_sets['Mechanism Bones'])

    ################################
    # Spline IK functions.

    def base__relink(self):
        # Transfer and relink constraints and their drivers
        assert self.tweak_bone

        org_bi = self.bones_org[0]
        if not self.params.tweak.constraints_additive:
            self.tweak_bone.clear_constraints()
        for con_info in org_bi.constraint_infos[:]:
            self.tweak_bone.constraint_infos.append(con_info)
            org_bi.constraint_infos.remove(con_info)

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        # We use the collections the actual bone itself is assigned to.
        return False

    ##############################
    # Parameters

    @classmethod
    def draw_control_params(cls, layout, context, params):
        """Create the ui for the rig parameters."""

        cls.draw_control_label(layout, "Tweak")
        cls.draw_prop(context, layout, params.tweak, "constraints_additive")
        cls.draw_prop(context, layout, params.tweak, "ensure_free")
        cls.draw_prop(context, layout, params.tweak, "transforms")
        cls.draw_prop(context, layout, params.tweak, "locks")
        cls.draw_prop(context, layout, params.tweak, "rot_mode")
        cls.draw_prop(context, layout, params.tweak, "shape")
        cls.draw_prop(context, layout, params.tweak, "collections")
        cls.draw_prop(context, layout, params.tweak, "color_palette")
        cls.draw_prop(context, layout, params.tweak, "ik_settings")
        cls.draw_prop(context, layout, params.tweak, "bbone_props")
        cls.draw_prop(context, layout, params.tweak, "custom_props")


class Params(PropertyGroup):
    constraints_additive: BoolProperty(
        name="Additive Constraints",
        description="Add the constraints of this bone to the generated bone's constraints. When disabled, we replace the constraints instead",
        default=True,
    )
    transforms: BoolProperty(
        name="Transforms",
        description="Replace the matching generated bone's transforms with this bone's transforms",  # An idea: when this is False, let the generation script affect the metarig - and move this bone, to where it is in the generated rig.
        default=False,
    )
    locks: BoolProperty(
        name="Locks",
        description="Replace the matching generated bone's transform locks with this bone's transform locks",
        default=True,
    )
    rot_mode: BoolProperty(
        name="Rotation Mode",
        description="Set the matching generated bone's rotation mode to this bone's rotation mode",
        default=False,
    )
    shape: BoolProperty(
        name="Bone Shape",
        description="Replace the matching generated bone's shape with this bone's shape",
        default=False,
    )
    collections: BoolProperty(
        name="Collections",
        description="Assign the matching generated bone to the collections of this tweak bone",
        default=False,
    )
    color_palette: BoolProperty(
        name="Color Palette",
        description="Set the generated bone's colors to this bone's colors",
        default=False,
    )
    ik_settings: BoolProperty(
        name="IK Settings",
        description="Copy IK settings from this bone to the generated bone",
        default=False,
    )
    bbone_props: BoolProperty(
        name="B-Bone Settings",
        description="Copy B-Bone settings from this bone to the generated bone",
        default=False,
    )
    custom_props: BoolProperty(
        name="Custom Properties",
        description="Copy custom properties from this bone to the generated bone",
        default=False,
    )
    ensure_free: BoolProperty(
        name="Move Constraints To Parent",
        description='If this bone has any constraints, move them to a parent bone prefixed with "CON", unless the constraint name starts with "KEEP"',
        default=False,
    )


RIG_COMPONENT_CLASS = Component_TweakBone
