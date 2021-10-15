from bpy.types import (PoseBone, PropertyGroup, ID,
                       bpy_prop_array, bpy_prop_collection,
                       Operator)

from rigify.ui import VIEW3D_MT_rigify
from rigify.utils.naming import mirror_name


def copy_property_group(from_pg: PropertyGroup, to_pg: PropertyGroup, x_mirror=False):
    """Copy the values of one PropertyGroup to another PropertyGroup of the same kind.
    Optionally, flip strings where possible, eg. "Bone.L" -> "Bone.R".
    """
    for key in dir(from_pg):
        # NOTE: Must use dir() instead of items() because the latter only
        # contains the properties whose values were actually modified.
        if key.startswith("__") or key in ['rna_type', 'bl_rna']:
            continue

        value = getattr(from_pg, key)

        if isinstance(value, bpy_prop_collection):
            # If the property is a CollectionProperty, we can use recursion.
            from_cp = value
            to_cp = getattr(to_pg, key)
            to_cp.clear()
            for from_entry in from_cp:
                to_entry = to_cp.add()
                copy_property_group(from_entry, to_entry, x_mirror)
            continue
        elif isinstance(value, bpy_prop_array):
            # If the property is any VectorProperty.
            setattr(to_pg, key, value[:])
            continue

        # Remaining simple cases: bools, ints, floats, strings and enums.
        if isinstance(value, str) and x_mirror:
            value = mirror_name(value)

        setattr(to_pg, key, value)


def copy_rigify_params(from_bone: PoseBone, to_bone: PoseBone, x_mirror=False):
    to_bone.rigify_type = from_bone.rigify_type
    copy_property_group(from_bone.rigify_parameters,
                        to_bone.rigify_parameters, x_mirror)


class MirrorRigifyParameters(Operator):
    """Mirror Rigify type and parameters of selected bones to the opposite side. Names should end in L/R"""

    bl_idname = "pose.rigify_mirror_parameters"
    bl_label = "Mirror Rigify Parameters"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        pbones = context.selected_pose_bones
        if not obj or not pbones:
            return False
        is_pose_mode_armature = (obj.type == 'ARMATURE' and obj.mode == 'POSE')
        is_any_bone_selected = len(pbones) > 0
        is_any_bone_mirrorable = any(
            [mirror_name(b.name) != b.name for b in pbones])
        return is_pose_mode_armature and is_any_bone_selected and is_any_bone_mirrorable

    def execute(self, context):
        rig = context.object

        num_mirrored = 0
        for pb in context.selected_pose_bones:
            flip_bone = rig.pose.bones.get(mirror_name(pb.name))
            if flip_bone == pb or not flip_bone:
                continue
            if flip_bone.bone.select:
                self.report(
                    {'ERROR'}, f"Bone {pb.name} selected on both sides, mirroring would be ambiguous, aborting. Only select the left or right side, not both!")
                return {'CANCELLED'}

            copy_rigify_params(pb, flip_bone, x_mirror=True)
            num_mirrored += 1

        self.report({'INFO'}, f"Mirrored parameters of {num_mirrored} bones.")

        return {'FINISHED'}


class CopyRigifyParameters(Operator):
    """Copy Rigify type and parameters from active to selected bones"""

    bl_idname = "pose.rigify_copy_parameters"
    bl_label = "Copy Rigify Parameters to Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or not context.selected_pose_bones:
            return False
        is_pose_mode_armature = (obj.type == 'ARMATURE' and obj.mode == 'POSE')
        is_bones_selected = len(context.selected_pose_bones) > 1
        is_active_bone_selected = context.active_pose_bone in context.selected_pose_bones
        return is_pose_mode_armature and is_bones_selected and is_active_bone_selected

    def execute(self, context):
        active_bone = context.active_pose_bone

        num_copied = 0
        for pb in context.selected_pose_bones:
            if pb == active_bone:
                continue
            copy_rigify_params(active_bone, pb)
            num_copied += 1

        self.report({'INFO'}, f"Copied {active_bone.rigify_type} parameters to {num_copied} bones.")

        return {'FINISHED'}


def draw_copy_mirror_ops(self, context):
    layout = self.layout
    if context.mode == 'POSE':
        layout.operator(CopyRigifyParameters.bl_idname,
                        icon='DUPLICATE', text="Copy Parameters to Selected")
        layout.operator(MirrorRigifyParameters.bl_idname,
                        icon='MOD_MIRROR', text="Mirror Parameters")


def register():
    from bpy.utils import register_class
    register_class(MirrorRigifyParameters)
    register_class(CopyRigifyParameters)

    VIEW3D_MT_rigify.append(draw_copy_mirror_ops)


def unregister():
    from bpy.utils import unregister_class
    unregister_class(MirrorRigifyParameters)
    unregister_class(CopyRigifyParameters)

    VIEW3D_MT_rigify.remove(draw_copy_mirror_ops)
