"""
This is currently intended to be used with the Pie Menu Editor add-on.
In future, we could create our own pie menu and hotkey UI.
"""

import bpy
from bpy.types import Menu, Bone, EditBone
from bpy.props import BoolProperty
from bpy.utils import flip_name
from ..generation.cloudrig import register_hotkey, CloudRigOperator


def get_active_bone(context):
    if context.object.mode == 'POSE':
        if context.active_pose_bone:
            return context.active_pose_bone.bone
        else:
            return context.active_bone
    elif context.object.mode == 'EDIT':
        return context.active_bone


def get_selected_bones(context, exclude_active=False) -> list[Bone]:
    if not context.object or not context.object.type == 'ARMATURE':
        return []
    bones = []
    if context.object.mode == 'POSE':
        bones = [pb.bone for pb in context.selected_pose_bones]
    elif context.object.mode == 'EDIT':
        # We can't use context.selected_editable_bones because
        # it actually includes non-selected bones when use_mirror_x==True.
        bones = [eb for eb in context.object.data.edit_bones if eb.select]

    if exclude_active:
        bones.remove(get_active_bone(context))

    return bones


class GenericBoneOperator:
    @classmethod
    def poll(cls, context):
        return (
            context.object
            and context.object.type == 'ARMATURE'
            and context.object.mode in {'POSE', 'EDIT'}
        )

    @staticmethod
    def get_selected_pose_bones(context):
        if context.object.mode == 'POSE':
            return context.selected_pose_bones
        elif context.object.mode == 'EDIT':
            return [
                context.object.data.bones.get(eb.name)
                for eb in context.selected_editable_bones
                if eb.name in context.object.data.bones
            ]

    def get_bones_to_affect(self, context) -> set[str]:
        rig = context.active_object
        mode = rig.mode
        bone_names = {b.name for b in get_selected_bones(context)}
        if mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        if rig.data.use_mirror_x:
            for bone_name in set(bone_names):
                flipped_name = flip_name(bone_name)
                if bone_name == flipped_name:
                    continue
                if flipped_name in bone_names:
                    continue
                flipped_bone = rig.data.bones.get(flipped_name)
                if not flipped_bone:
                    continue
                bone_names.add(flipped_name)

        return bone_names

    def affect_bones(self, context) -> set[str]:
        """Returns list of bone names that were actually affected."""
        rig = context.active_object
        mode = rig.mode
        bones_to_affect = self.get_bones_to_affect(context)

        affected_bones = set()
        for bone_name in bones_to_affect:
            eb = context.object.data.edit_bones[bone_name]
            was_affected = self.affect_bone(eb)
            if was_affected:
                affected_bones.add(bone_name)

        bpy.ops.object.mode_set(mode=mode)
        return affected_bones

    def affect_bone(self, eb: EditBone) -> bool:
        """Return whether the bone was indeed affected."""
        raise NotImplementedError


class POSE_OT_disconnect_bones(GenericBoneOperator, CloudRigOperator):
    """Disconnect selected bones"""

    bl_idname = "pose.disconnect_selected"
    bl_label = "Disconnect Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        for b in get_selected_bones(context):
            if b.use_connect:
                return True
        else:
            return False

    def affect_bone(self, eb: EditBone) -> bool:
        if eb.parent:
            eb.parent = None
            return True
        return False

    def execute(self, context):
        affected = self.affect_bones(context)
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Disconnected {len(affected)} bone{plural}.")
        return {'FINISHED'}


class POSE_OT_unparent_bones(GenericBoneOperator, CloudRigOperator):
    """Unparent selected bones"""

    bl_idname = "pose.unparent_selected"
    bl_label = "Unparent Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        for b in get_selected_bones(context):
            if b.parent:
                return True

        return False

    def affect_bone(self, eb: EditBone) -> bool:
        if eb.parent:
            eb.parent = None
            return True
        return False

    def execute(self, context):
        affected = self.affect_bones(context)
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Unparented {len(affected)} bone{plural}.")
        return {'FINISHED'}


class POSE_OT_parent_active_to_all_selected(GenericBoneOperator, CloudRigOperator):
    """Parent active bone to all selected bones using Armature constraint"""

    bl_idname = "pose.parent_active_to_all_selected"
    bl_label = "Parent Active to All Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        return len(get_selected_bones(context)) > 1 and get_active_bone(context)

    def execute(self, context):
        mode = context.object.mode
        if mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        context.active_bone.parent = None
        bpy.ops.object.mode_set(mode=mode)

        active_bone = get_active_bone(context)

        rig = context.object
        active_pb = rig.pose.bones[active_bone.name]

        # If there is an existing Armature constraint, preserve it. (For position in stack, name, and settings)
        arm_con = None
        for c in active_pb.constraints:
            if c.type == 'ARMATURE':
                c.targets.clear()
                arm_con = c
                break
        if not arm_con:
            arm_con = active_pb.constraints.new(type='ARMATURE')

        for bone in get_selected_bones(context, exclude_active=True):
            target = arm_con.targets.new()
            target.target = rig
            target.subtarget = bone.name

        plural = "s" if len(arm_con.targets) != 1 else ""
        self.report(
            {'INFO'},
            f'Parented "{active_pb.name}" to {len(arm_con.targets)} bone{plural} using Armature constraint.',
        )
        return {'FINISHED'}


class POSE_OT_parent_selected_to_active(GenericBoneOperator, CloudRigOperator):
    """Parent selected bones to the active one"""

    bl_idname = "pose.parent_selected_to_active"
    bl_label = "Parent Selected Bones To Active"
    bl_options = {'REGISTER', 'UNDO'}

    use_connect: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        return len(get_selected_bones(context)) > 1 and get_active_bone(context)

    def parent_edit_bones(self, parent, bones_to_parent):
        parent.hide = False
        for eb in bones_to_parent:
            eb.hide = False
            if parent.parent == eb:
                # When inverting a parenting relationship (child becomes the parent),
                # set the old child's parent as the new parent's parent.
                # Otherwise, the parent will become parentless, which is usually not desired.
                parent.use_connect = False
                parent.parent = eb.parent
            if (eb.head - parent.tail).length > 0.0001:
                # If use_connect of this child was previously True, but now the parent is
                # somewhere far away, set that flag to False, so the child doesn't move.
                eb.use_connect = False
            if self.use_connect:
                # If the user explicitly asked for connecting the child to the parent, do so.
                eb.use_connect = True
            eb.parent = parent

    def execute(self, context):
        rig = context.object
        mode = rig.mode
        bpy.ops.object.mode_set(mode='EDIT')
        parent = get_active_bone(context)
        parent_name = parent.name

        bones_to_parent = get_selected_bones(context, exclude_active=True)
        self.parent_edit_bones(parent, bones_to_parent)

        if rig.data.use_mirror_x:
            flipped_parent = rig.data.edit_bones.get(flip_name(parent.name))
            if flipped_parent:
                flipped_bones_to_parent = {
                    rig.data.edit_bones.get(flip_name(eb.name))
                    for eb in bones_to_parent
                }
                flipped_bones_to_parent = [eb for eb in flipped_bones_to_parent if eb]
                self.parent_edit_bones(flipped_parent, flipped_bones_to_parent)

        bpy.ops.object.mode_set(mode=mode)
        plural = "s" if len(bones_to_parent) != 1 else ""
        message = f'Parented {len(bones_to_parent)} bone{plural} to "{parent_name}".'
        if rig.data.use_mirror_x:
            message += "(Symmetrized!)"
        self.report(
            {'INFO'},
            message,
        )
        return {'FINISHED'}


class POSE_OT_parent_object_to_selected_bones(CloudRigOperator):
    """Parent object to selected bones"""

    bl_idname = "pose.parent_object_to_selected_bones"
    bl_label = "Parent Selected Objects to Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            len(get_selected_bones(context)) > 0 and len(context.selected_objects) > 1
        )

    def execute(self, context):
        rig = context.object
        target_objs = [o for o in context.selected_objects if o != rig]
        if not target_objs:
            return {'CANCELLED'}

        bones = get_selected_bones(context, exclude_active=False)
        for obj in target_objs:
            arm_con = None
            for c in obj.constraints:
                if c.type == 'ARMATURE':
                    c.targets.clear()
                    arm_con = c
                    break
            if not arm_con:
                arm_con = obj.constraints.new(type='ARMATURE')

            for bone in bones:
                target = arm_con.targets.new()
                target.target = rig
                target.subtarget = bone.name
            obj.parent = rig
            obj.parent_type = 'OBJECT'

        objs = obj.name if len(target_objs) == 1 else f"{len(target_objs)} objects"
        plural_bone = "s" if len(bones) != 1 else ""
        self.report({'INFO'}, f"Parented {objs} to {len(bones)} bone{plural_bone}.")
        return {'FINISHED'}


class CLOUDRIG_MT_PIE_bone_parenting(Menu):
    bl_label = "Bone Parenting"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        # 1) < Unparent Selected bones.
        pie.operator(
            'pose.unparent_selected',
            text="Clear Parent",
            icon='X',
        )

        # 2) > Parent Selected to Active.
        pie.operator(
            'pose.parent_selected_to_active',
            text="Selected to Active",
            icon='CON_CHILDOF',
        ).use_connect = False

        # 3) V & ^ Leave empty.
        pie.separator()
        pie.separator()

        # 5) <^ Disconnect Bones.
        pie.operator(
            'pose.disconnect_selected',
            text="Disconnect",
            icon='UNLINKED',
        )

        # 6) ^> Parent Active to All Selected
        pie.operator(
            'pose.parent_active_to_all_selected',
            text="Active to All Selected",
            icon='PARTICLE_DATA',
        )

        # 7) <v Parent Object to All Selected
        pie.operator(
            'pose.parent_object_to_selected_bones',
            text="Parent Object to All Selected",
            icon='OBJECT_DATA',
        )

        # 8) v> Parent and Connect.
        pie.operator(
            'pose.parent_selected_to_active',
            text="Parent & Connect",
            icon='LINKED',
        ).use_connect = True


registry = [
    POSE_OT_disconnect_bones,
    POSE_OT_unparent_bones,
    POSE_OT_parent_active_to_all_selected,
    POSE_OT_parent_selected_to_active,
    POSE_OT_parent_object_to_selected_bones,
    CLOUDRIG_MT_PIE_bone_parenting,
]


def register():
    for key_cat, space_type in {
        ('Pose', 'VIEW_3D'),
        ('Weight Paint', 'EMPTY'),
        ('Armature', 'VIEW_3D'),
    }:
        register_hotkey(
            'wm.call_menu_pie',
            hotkey_kwargs={'type': "P", 'value': "PRESS"},
            key_cat=key_cat,
            space_type=space_type,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_bone_parenting'},
        )
