# SPDX-License-Identifier: GPL-3.0-or-later

"""
This is currently intended to be used with the Pie Menu Editor add-on.
In future, we could create our own pie menu and hotkey UI.
"""

import bpy
from bpy.types import Menu, EditBone, PoseBone, Object, Operator
from bpy.utils import flip_name
from ..bs_utils.hotkeys import register_hotkey
from ..utils.rig import get_selected_bone_tuples, get_current_rigs, get_active_bone


class GenericBoneOperator:
    @classmethod
    def poll(cls, context):
        if not (context.active_object and context.active_object.type == 'ARMATURE'):
            cls.poll_message_set("No active armature.")
            return False
        if not context.active_object.mode in {'POSE', 'EDIT', 'WEIGHT_PAINT'}:
            cls.poll_message_set("Must be in Pose / Edit / Weight Paint mode.")
            return False
        return True

    def get_bones_to_affect(self, context) -> list[tuple[Object, EditBone]]:
        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        ebone_tuples = get_selected_bone_tuples(context)
        for rig, ebone in ebone_tuples[:]:
            rig_data = ebone.id_data
            if rig_data.use_mirror_x:
                flipped_name = flip_name(ebone.name)
                if ebone.name == flipped_name:
                    continue
                flipped_ebone = rig_data.edit_bones.get(flipped_name)
                if not flipped_ebone:
                    continue
                tup = (rig, flipped_ebone)
                if tup not in ebone_tuples:
                    ebone_tuples.append((rig, flipped_ebone))

        return ebone_tuples

    def affect_bones(self, context) -> set[str]:
        """Returns list of bone names that were actually affected."""
        mode = context.active_object.mode
        ebones_to_affect = self.get_bones_to_affect(context)

        affected_bones_names = set()
        for rig, ebone in list(ebones_to_affect):
            bone_name = ebone.name
            was_affected = self.affect_bone(rig, ebone)
            if was_affected:
                affected_bones_names.add(bone_name)

        bpy.ops.object.mode_set(mode=mode)
        return affected_bones_names

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        """Return whether the bone was indeed affected."""
        raise NotImplementedError


class POSE_OT_disconnect_bones(GenericBoneOperator, Operator):
    """Disconnect selected bones"""

    bl_idname = "pose.disconnect_selected"
    bl_label = "Disconnect Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        for rig, bone in get_selected_bone_tuples(context):
            if bone.use_connect:
                return True

        cls.poll_message_set("None of the selected bones are connected.")
        return False

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        if eb.use_connect:
            eb.use_connect = False
            return True
        return False

    def execute(self, context):
        affected = self.affect_bones(context)
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Disconnected {len(affected)} bone{plural}.")
        return {'FINISHED'}


class POSE_OT_unparent_bones(GenericBoneOperator, Operator):
    """Unparent selected bones"""

    bl_idname = "pose.unparent_selected"
    bl_label = "Unparent Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        for rig, bone in get_selected_bone_tuples(context):
            # Could be EditBone or regular bone here, doesn't matter.
            if bone.parent:
                return True

        cls.poll_message_set("None of the selected bones have a parent.")
        return False

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        if eb.parent:
            eb.parent = None
            return True
        return False

    def execute(self, context):
        affected = self.affect_bones(context)
        plural = "s" if len(affected) != 1 else ""
        self.report({'INFO'}, f"Unparented {len(affected)} bone{plural}.")
        return {'FINISHED'}


class POSE_OT_parent_active_to_all_selected(GenericBoneOperator, Operator):
    """Parent active bone to all selected bones using Armature constraint"""

    bl_idname = "pose.parent_active_to_all_selected"
    bl_label = "Parent Active to All Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        if not len(get_selected_bone_tuples(context)) > 1:
            cls.poll_message_set("At least two bones must be selected.")
            return False
        if not get_active_bone(context):
            cls.poll_message_set("There is no active bone.")
            return False
        return True

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

        for pbone in context.selected_pose_bones:
            if pbone == active_pb:
                continue
            target = arm_con.targets.new()
            target.target = pbone.id_data
            target.subtarget = pbone.name

        plural = "s" if len(arm_con.targets) != 1 else ""
        self.report(
            {'INFO'},
            f'Parented "{active_pb.name}" to {len(arm_con.targets)} bone{plural} using Armature constraint.',
        )
        return {'FINISHED'}


class POSE_OT_parent_selected_to_active(GenericBoneOperator, Operator):
    """Parent selected bones to the active one"""

    bl_idname = "pose.parent_selected_to_active"
    bl_label = "Parent Selected Bones To Active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll_parenting(cls, context):
        if not super().poll(context):
            return False
        active_bone = get_active_bone(context)
        if type(active_bone) == PoseBone:
            active_bone = active_bone.bone
        if not active_bone:
            cls.poll_message_set("There is no active bone.")
            return False
        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        if len(bone_tuples_to_parent) < 1:
            cls.poll_message_set("At least two bones must be selected.")
            return False
        if any([b.id_data != active_bone.id_data for rig, b in bone_tuples_to_parent]):
            cls.poll_message_set("All selected bones must be from the same armature.")
            return False
        return True

    @classmethod
    def poll(cls, context):
        poll_parenting = cls.poll_parenting(context)
        if not poll_parenting:
            return False

        active_bone = get_active_bone(context)
        if type(active_bone) == PoseBone:
            active_bone = active_bone.bone
        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        if all([b.parent == active_bone for rig, b in bone_tuples_to_parent]):
            cls.poll_message_set(
                "Selected bones are already parented to the active one."
            )
            return False
        return True

    def parent_edit_bones(
        self, parent_eb, bone_tuples_to_parent: list[tuple[Object, EditBone]]
    ):
        parent_eb.hide = False
        for rig, child_eb in bone_tuples_to_parent:
            self.parent_edit_bone(parent_eb, child_eb)

    def parent_edit_bone(self, parent_eb, child_eb):
        child_eb.hide = False
        if parent_eb.parent == child_eb:
            # When inverting a parenting relationship (child becomes the parent),
            # set the old child's parent as the new parent's parent.
            # Otherwise, the parent will become parentless, which is usually not desired.
            parent_eb.use_connect = False
            parent_eb.parent = child_eb.parent
        if (child_eb.head - parent_eb.tail).length > 0.0001:
            # If use_connect of this child was previously True, but now the parent is
            # somewhere far away, set that flag to False, so the child doesn't move.
            child_eb.use_connect = False
        child_eb.parent = parent_eb

    def execute(self, context):
        rig = context.object
        mode = rig.mode
        bpy.ops.object.mode_set(mode='EDIT')
        parent = get_active_bone(context)
        parent_name = parent.name

        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        self.parent_edit_bones(parent, bone_tuples_to_parent)

        flipped_bone_tuples_to_parent = []
        if rig.data.use_mirror_x:
            flipped_parent = rig.data.edit_bones.get(flip_name(parent.name))
            if flipped_parent:
                flipped_bone_tuples_to_parent = []
                for rig, eb in bone_tuples_to_parent:
                    flipped_eb = rig.data.edit_bones.get(flip_name(eb.name))
                    if not flipped_eb or flipped_eb == eb:
                        continue
                    flipped_bone_tuples_to_parent.append((rig, flipped_eb))
                self.parent_edit_bones(flipped_parent, flipped_bone_tuples_to_parent)

        bpy.ops.object.mode_set(mode=mode)
        plural = "s" if len(bone_tuples_to_parent) != 1 else ""
        message = (
            f'Parented {len(bone_tuples_to_parent)} bone{plural} to "{parent_name}".'
        )
        if rig.data.use_mirror_x and flipped_bone_tuples_to_parent:
            message += "(Symmetrized!)"
        self.report(
            {'INFO'},
            message,
        )
        return {'FINISHED'}


class POSE_OT_parent_and_connect(POSE_OT_parent_selected_to_active):
    """Parent and connect selected bones to the active one"""

    bl_idname = "pose.parent_and_connect"
    bl_label = "Parent & Connect Selected Bones To Active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        poll_parenting = cls.poll_parenting(context)
        if not poll_parenting:
            return False

        active_bone = get_active_bone(context)
        if type(active_bone) == PoseBone:
            active_bone = active_bone.bone
        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        if all(
            [
                b.parent == active_bone and b.use_connect
                for rig, b in bone_tuples_to_parent
            ]
        ):
            cls.poll_message_set(
                "Selected bones are already parented and connected to the active one."
            )
            return False
        return True

    def parent_edit_bone(self, parent_eb, child_eb):
        super().parent_edit_bone(parent_eb, child_eb)
        offset = parent_eb.tail - child_eb.head
        child_eb.tail += offset
        child_eb.head += offset
        child_eb.use_connect = True


class POSE_OT_parent_object_to_selected_bones(Operator):
    """Parent object to selected bones"""

    bl_idname = "pose.parent_object_to_selected_bones"
    bl_label = "Parent Selected Objects to Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not len(get_selected_bone_tuples(context)) > 0:
            cls.poll_message_set("At least one bone must be selected.")
            return False
        if not len(context.selected_objects) > 1:
            cls.poll_message_set("At least one object outside of the armature must be selected.")
            return False
        return True

    def execute(self, context):
        rig = context.object
        target_objs = [o for o in context.selected_objects if o.mode != 'POSE']
        if not target_objs:
            return {'CANCELLED'}

        pbones = context.selected_pose_bones
        for obj in target_objs:
            arm_con = None
            for c in obj.constraints:
                if c.type == 'ARMATURE':
                    c.targets.clear()
                    arm_con = c
                    break
            if not arm_con:
                arm_con = obj.constraints.new(type='ARMATURE')

            for pbone in pbones:
                target = arm_con.targets.new()
                target.target = pbone.id_data
                target.subtarget = pbone.name
            obj.parent = rig
            obj.parent_type = 'OBJECT'

        objs = obj.name if len(target_objs) == 1 else f"{len(target_objs)} objects"
        plural_bone = "s" if len(pbones) != 1 else ""
        self.report({'INFO'}, f"Parented {objs} to {len(pbones)} bone{plural_bone}.")
        return {'FINISHED'}


class POSE_OT_separate_selected_bones(Operator):
    """Separate the selected bones into a new armature object"""

    bl_idname = "pose.separate_selected_bones"
    bl_label = "Separate Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if len(list(get_current_rigs(context))) != 1:
            cls.poll_message_set("Only one selected armature is supported.")
            return False
        if len(get_selected_bone_tuples(context)) == 0:
            cls.poll_message_set("No bones are selected.")
            return False
        return True

    def execute(self, context):
        bone_tuples = get_selected_bone_tuples(context)
        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        for rig, bone in bone_tuples:
            edit_bone = rig.data.edit_bones.get(bone.name)
            edit_bone.hide = False
            edit_bone.select = True

        selected_objects = set(context.selected_objects)
        bpy.ops.armature.separate()
        bpy.ops.object.mode_set(mode='OBJECT')
        new_selected_objects = set(context.selected_objects)
        bpy.ops.object.select_all(action='DESELECT')

        for obj in new_selected_objects:
            if obj not in selected_objects:
                context.view_layer.objects.active = obj
                obj.select_set(True)
                break

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
        )

        # 3) V Separate
        pie.operator(
            'pose.separate_selected_bones', text="Separate Selected", icon='UNLINKED'
        )

        # 4) ^ Leave empty.
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
            'pose.parent_and_connect',
            text="Parent & Connect",
            icon='LINKED',
        )


registry = [
    POSE_OT_disconnect_bones,
    POSE_OT_unparent_bones,
    POSE_OT_parent_active_to_all_selected,
    POSE_OT_parent_and_connect,
    POSE_OT_parent_selected_to_active,
    POSE_OT_parent_object_to_selected_bones,
    POSE_OT_separate_selected_bones,
    CLOUDRIG_MT_PIE_bone_parenting,
]


def register():
    for keymap_name in ('Pose', 'Weight Paint', 'Armature'):
        register_hotkey(
            'wm.call_menu_pie',
            hotkey_kwargs={'type': "P", 'value': "PRESS"},
            keymap_name=keymap_name,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_bone_parenting'},
        )
