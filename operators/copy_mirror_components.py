# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import PoseBone, bpy_prop_collection, PropertyGroup, Object
from bpy.utils import flip_name

from ..generation.cloudrig import CloudRigOperator


class POSE_OT_cloudrig_symmetrize_components(CloudRigOperator):
    """Mirror rig component type and parameters of selected bones to the opposite side. Names should end in L/R"""

    bl_idname = "pose.cloudrig_symmetrize_components"
    bl_label = "Symmetrize Components"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            cls.poll_message_set("Active armature must be in pose mode.")
            return False
        sel_bones = context.selected_pose_bones
        if not sel_bones:
            cls.poll_message_set("At least one bone must be selected.")
            return False
        for pb in sel_bones:
            mirrored_name = flip_name(pb.name)
            if mirrored_name != pb.name and mirrored_name in obj.pose.bones:
                return True
        return False

    def execute(self, context):
        rig = context.object

        num_mirrored = 0

        # First make sure that all selected bones can be mirrored unambiguously.
        for from_bone in context.selected_pose_bones:
            to_bone = rig.pose.bones.get(flip_name(from_bone.name))
            if not to_bone:
                # Bones without an opposite will just be ignored.
                continue
            if to_bone != from_bone and to_bone.bone.select:
                self.report(
                    {'ERROR'},
                    f"Bone {from_bone.name} selected on both sides, mirroring would be ambiguous, "
                    f"aborting. Only select the left or right side, not both!",
                )
                return {'CANCELLED'}

        # Then mirror the parameters.
        for from_bone in context.selected_pose_bones:
            to_bone = rig.pose.bones.get(flip_name(from_bone.name))
            if to_bone == from_bone or not to_bone:
                # Bones without an opposite will just be ignored.
                continue

            copy_property_group(from_bone.cloudrig_component, to_bone.cloudrig_component, x_mirror=True)
            num_mirrored += 1

        self.report({'INFO'}, f"Mirrored parameters of {num_mirrored} bones.")

        return {'FINISHED'}


class POSE_OT_cloudrig_copy_component(CloudRigOperator):
    """Copy rig component type parameters from active to selected bones"""

    bl_idname = "pose.cloudrig_copy_component"
    bl_label = "Copy Component to Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
            cls.poll_message_set("Active armature must be in pose mode.")
            return False

        active = context.active_pose_bone
        if not active or not active.cloudrig_component.component_type:
            cls.poll_message_set("Active bone has no CloudRig Component assigned.")
            return False

        select = context.selected_pose_bones
        if len(select) < 2:
            cls.poll_message_set("At least two bones must be selected.")
            return False

        if active not in select:
            cls.poll_message_set("Make sure the active bone is also selected.")
            return False

        return True

    def execute(self, context):
        from_bone = context.active_pose_bone

        num_copied = 0
        for to_bone in context.selected_pose_bones:
            if to_bone == from_bone:
                continue
            num_copied += 1
            copy_property_group(from_bone.cloudrig_component, to_bone.cloudrig_component, x_mirror=True)

        self.report(
            {'INFO'},
            f"Copied {from_bone.cloudrig_component.component_type} parameters to {num_copied} bones.",
        )

        return {'FINISHED'}


def copy_property_group(src_pg: PropertyGroup, dst_pg: PropertyGroup, x_mirror=False):
    """
    Copy the values from one PropertyGroup into another of the same type.
    Optionally, X-mirror names (e.g., ".L" <-> ".R") in strings and Object references.
    """
    assert isinstance(dst_pg, PropertyGroup) and isinstance(src_pg, PropertyGroup)
    assert dst_pg.__class__ == src_pg.__class__

    for key in src_pg.bl_rna.properties.keys():
        if key in ('rna_type', 'bl_rna'):
            continue
        if not src_pg.is_property_set(key):
            dst_pg.property_unset(key)
            continue
        value = getattr(src_pg, key)
        if isinstance(value, bpy_prop_collection):
            dst_coll = getattr(dst_pg, key)
            dst_coll.clear()
            for src_entry in value:
                if isinstance(src_entry, PropertyGroup):
                    dst_entry = dst_coll.add()
                    copy_property_group(src_entry, dst_entry, x_mirror)
        elif isinstance(value, PropertyGroup):
            copy_property_group(value, getattr(dst_pg, key), x_mirror)
        elif src_pg.is_property_readonly(key):
            # This has to come after CollectionProperty and PropertyGroup checks, 
            # since they are technically read-only.
            continue
        elif isinstance(value, str):
            setattr(dst_pg, key, flip_name(value) if x_mirror else value)
        elif isinstance(value, Object):
            setattr(dst_pg, key, get_opposite_obj(value) if x_mirror else value)
        else:
            setattr(dst_pg, key, value)


def get_opposite_obj(obj: Object) -> Object:
    """Return the X-mirrored version of a Blender object by name (and library if linked)."""
    flipped_name = flip_name(obj.name)
    lib = obj.library
    return (
        bpy.data.objects.get((lib, flipped_name)) if lib else
        bpy.data.objects.get(flipped_name)
    ) or obj


def draw_copy_mirror_ops(self, context):
    layout = self.layout
    if context.mode == 'POSE':
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_copy_component.bl_idname,
            icon='DUPLICATE',
            text="Copy Rig Component",
        )
        layout.operator(
            POSE_OT_cloudrig_symmetrize_components.bl_idname,
            icon='MOD_MIRROR',
            text="Symmetrize Rig Component",
        )


# =============================================
# Registration

registry = [POSE_OT_cloudrig_symmetrize_components, POSE_OT_cloudrig_copy_component]
