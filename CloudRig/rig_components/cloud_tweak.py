# SPDX-License-Identifier: GPL-3.0-or-later

from bpy.app.translations import pgettext_iface as iface_
from bpy.app.translations import pgettext_n as n_
from bpy.app.translations import pgettext_rpt as rpt_
from bpy.props import BoolProperty
from bpy.types import PropertyGroup

from ..rig_component_features.bone_info import BoneInfo
from ..rig_component_features.overlay_painter import no_overlay
from .cloud_base import Component_Base


class Component_TweakBone(Component_Base):
    """Tweak a single bone with the same name as this bone in the Target Rig."""

    ui_name = "Bone Tweak"
    parent_switch_behaviour = n_("The active parent will own the tweaked bone.")

    keep_original_bones = False
    keep_original_bones_collections = True
    keep_original_bones_colors = True

    ################################
    # Inherited functions.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bone_to_tweak = None

    def base__load_metarig_bones(self) -> dict[str, BoneInfo]:
        bone_infos = super().base__load_metarig_bones()
        if len(bone_infos) > 1:
            self.add_log(
                rpt_("Tweak does not support chains"),
                description=rpt_("The Bone Tweak component type will only affect the first bone of the chain. " \
                    "To affect the rest of the bone chain, you must assign the Bone Tweak type to each bone.")
            )

        bone_info_tuple = [(key, value) for key, value in bone_infos.items()][0]
        self.original_name, self_bone = bone_info_tuple
        self_bone.name += "_Tweak"
        return bone_infos

    def create_component_interactions(self, context):
        meta_pbone = self.metarig_base_pbone
        org_boneinfo = self.bones_org[0]
        self.bone_to_tweak = bone_to_tweak = self.generator.find_bone_info(self.original_name)

        if not self.bone_to_tweak:
            self.add_log(
                rpt_("No bone to tweak"),
                description=rpt_('Could not find a bone called "{bone}" on the Target Rig. ' \
                    'If it exists, ensure this Tweak component is generated AFTER the component you want to tweak.'
                ).format(bone=self.original_name),
                operator='object.cloudrig_rename_bone',
                op_kwargs={'old_name': self.original_name},
            )
            return

        self.root_bone = self.bone_to_tweak  # Allow parenting parameters to work

        if self.params.tweak.transforms:
            bone_to_tweak.head = org_boneinfo.head.copy()
            bone_to_tweak.tail = org_boneinfo.tail.copy()
            bone_to_tweak.roll = org_boneinfo.roll
            bone_to_tweak.bbone_x = org_boneinfo.bbone_x
            bone_to_tweak.bbone_z = org_boneinfo.bbone_z

        if self.params.tweak.locks:
            bone_to_tweak.lock_location = meta_pbone.lock_location[:]
            bone_to_tweak.lock_rotation = meta_pbone.lock_rotation[:]
            bone_to_tweak.lock_rotation_w = meta_pbone.lock_rotation_w
            bone_to_tweak.lock_scale = meta_pbone.lock_scale[:]

        if self.params.tweak.rot_mode:
            bone_to_tweak.rotation_mode = meta_pbone.rotation_mode

        if self.params.tweak.shape:
            bone_to_tweak.custom_shape = meta_pbone.custom_shape
            bone_to_tweak.custom_shape_wire_width = meta_pbone.custom_shape_wire_width
            bone_to_tweak.custom_shape_name = org_boneinfo.custom_shape_name
            bone_to_tweak.custom_shape_scale_xyz = meta_pbone.custom_shape_scale_xyz
            if bone_to_tweak.use_custom_shape_bone_size:
                scale_diff = bone_to_tweak.length / meta_pbone.length
                bone_to_tweak.custom_shape_scale_xyz = meta_pbone.custom_shape_scale_xyz * scale_diff
            bone_to_tweak.custom_shape_transform = meta_pbone.custom_shape_transform
            bone_to_tweak.use_custom_shape_bone_size = meta_pbone.use_custom_shape_bone_size
            bone_to_tweak.show_wire = org_boneinfo.show_wire
            bone_to_tweak.custom_shape_translation = meta_pbone.custom_shape_translation
            bone_to_tweak.custom_shape_rotation_euler = meta_pbone.custom_shape_rotation_euler
            bone_to_tweak.display_type = meta_pbone.bone.display_type
            if meta_pbone.custom_shape:
                self.add_to_widget_collection(context, meta_pbone.custom_shape)

        if self.params.tweak.collections:
            bone_to_tweak.collections = [coll.name for coll in meta_pbone.bone.collections]
        if self.params.tweak.color_palette:
            bone_to_tweak.color_palette_base = meta_pbone.bone.color.palette
            bone_to_tweak.color_palette_pose = meta_pbone.color.palette

        if self.params.tweak.ik_settings:
            bone_to_tweak.ik_stretch = meta_pbone.ik_stretch
            bone_to_tweak.lock_ik_x = meta_pbone.lock_ik_x
            bone_to_tweak.lock_ik_y = meta_pbone.lock_ik_y
            bone_to_tweak.lock_ik_z = meta_pbone.lock_ik_z
            bone_to_tweak.ik_stiffness_x = meta_pbone.ik_stiffness_x
            bone_to_tweak.ik_stiffness_y = meta_pbone.ik_stiffness_y
            bone_to_tweak.ik_stiffness_z = meta_pbone.ik_stiffness_z
            bone_to_tweak.use_ik_limit_x = meta_pbone.use_ik_limit_x
            bone_to_tweak.use_ik_limit_y = meta_pbone.use_ik_limit_y
            bone_to_tweak.use_ik_limit_z = meta_pbone.use_ik_limit_z
            bone_to_tweak.ik_min_x = meta_pbone.ik_min_x
            bone_to_tweak.ik_max_x = meta_pbone.ik_max_x
            bone_to_tweak.ik_min_y = meta_pbone.ik_min_y
            bone_to_tweak.ik_max_y = meta_pbone.ik_max_y
            bone_to_tweak.ik_min_z = meta_pbone.ik_min_z
            bone_to_tweak.ik_max_z = meta_pbone.ik_max_z

        if self.params.tweak.bbone_props:
            bone_to_tweak.bbone_segments = meta_pbone.bone.bbone_segments
            bone_to_tweak.bbone_x = meta_pbone.bone.bbone_x
            bone_to_tweak.bbone_z = meta_pbone.bone.bbone_z

        if self.params.tweak.custom_props:
            for prop_name in meta_pbone.keys():
                bone_to_tweak.custom_props[prop_name] = meta_pbone.id_properties_ui(prop_name).as_dict()

        super().create_component_interactions(context)

        bone_to_tweak.drivers_to_copy = org_boneinfo.drivers_to_copy

        if self.params.tweak.ensure_free:
            self.root_bone = self.ensure_free_transforms(bone_to_tweak, bone_set=self.bone_sets['Mechanism Bones'])

    ################################
    # Bone Tweak functions.

    @no_overlay
    def base__relink(self):
        # Transfer and relink constraints and their drivers
        assert self.bone_to_tweak

        meta_pbone = self.bones_org[0]
        if not self.params.tweak.constraints_additive:
            self.bone_to_tweak.clear_constraints()
        for con_info in meta_pbone.constraint_infos[:]:
            self.bone_to_tweak.constraint_infos.append(con_info)
            meta_pbone.constraint_infos.remove(con_info)

    @classmethod
    def is_bone_set_used(cls, context, rig, params, set_name):
        # We use the collections the actual bone itself is assigned to.
        return False

    ##############################
    # Parameters

    @classmethod
    def draw_control_params(cls, layout, context, component):
        params = component.params
        cls.draw_control_label(layout, iface_("Tweak"))
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
        description="Replace the matching generated bone's transforms with this bone's transforms",  # An idea: when this is False, let the generation script affect the Metarig - and move this bone, to where it is in the Target Rig.
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
        name="Ensure Free Transforms",
        description='If this bone has any drivers on its transform properties or constraints, move them to a parent bone prefixed with "CON", except for constraints whose name starts with "KEEP"',
        default=False,
    )


RIG_COMPONENT_CLASS = Component_TweakBone
