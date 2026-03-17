# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Bone, EditBone, Menu, Object, Operator, PoseBone
from bpy.utils import flip_name

from ..bs_utils.hotkeys import register_hotkey
from ..generation.cloudrig import active_rig
from ..utils.rig import get_active_bone, get_current_rigs, get_selected_bone_tuples


class GenericBoneOperator:
    @classmethod
    def poll(cls, context):
        rig = active_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            cls.poll_message_set("No active armature.")
            return False
        if rig.mode not in ('POSE', 'EDIT', 'WEIGHT_PAINT'):
            cls.poll_message_set("Must be in Pose / Edit / Weight Paint mode.")
            return False
        return True

    def get_ebones_to_affect(self, context) -> list[tuple[Object, Bone | EditBone]]:
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
        active_obj = None
        if mode == 'WEIGHT_PAINT':
            active_obj = context.active_object
            context.view_layer.objects.active = context.pose_object
        ebones_to_affect = self.get_ebones_to_affect(context)

        affected_bones_names = self.affect_ebones(context, ebones_to_affect)

        if mode == 'WEIGHT_PAINT':
            bpy.ops.object.mode_set(mode='POSE')
            context.view_layer.objects.active = active_obj
        bpy.ops.object.mode_set(mode=mode)
        return affected_bones_names

    def affect_ebones(self, context, ebones) -> set[str]:
        affected_bones_names = set()
        for rig, ebone in list(ebones):
            bone_name = ebone.name
            was_affected = self.affect_bone(rig, ebone)
            if was_affected:
                affected_bones_names.add(bone_name)
        return affected_bones_names

    def affect_bone(self, rig: Object, eb: EditBone) -> bool:
        """Return whether the bone was indeed affected."""
        raise NotImplementedError

    def execute(self, context):
        self.affect_bones(context)
        return {'FINISHED'}


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
        self.report({'INFO'}, "Disconnected {num_bones}.".format(num_bones=len(affected)))
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
        self.report({'INFO'}, "Unparented {num_bones}.".format(num_bones=len(affected)))
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
        if context.mode not in ('POSE', 'PAINT_WEIGHT'):
            cls.poll_message_set("Must be in Pose mode")
            return False
        if not len(get_selected_bone_tuples(context)) > 1:
            cls.poll_message_set("At least two bones must be selected.")
            return False
        if not get_active_bone(context):
            cls.poll_message_set("There is no active bone.")
            return False
        return True

    def get_ebones_to_affect(self, context) -> list[tuple[Object, Bone | EditBone]]:
        ebone_tuples = super().get_ebones_to_affect(context)
        ret = [tup for tup in ebone_tuples if tup[1].name == context.active_bone.name]
        return ret

    def affect_bone(self, rig: Object, ebone: EditBone):
        ebone.parent = None
        pbone = rig.pose.bones[ebone.name]

        # If there is an existing Armature constraint, preserve it. (For position in stack, name, and settings)
        arm_con = next((con for con in pbone.constraints if con.type == 'ARMATURE'), None)
        if not arm_con:
            arm_con = pbone.constraints.new(type='ARMATURE')
        arm_con.targets.clear()

        for target_rig, target_pb in self.selected_bones:
            if pbone == target_pb:
                continue
            target = arm_con.targets.new()
            target.target = target_rig
            target.subtarget = target_pb.name

        self.report(
            {'INFO'},
            'Parented "{bone}" to {count} bones using Armature constraint.'.format(bone=pbone.name, count=len(arm_con.targets)),
        )

    def execute(self, context):
        self.selected_bones = [(pb.id_data, pb) for pb in context.selected_pose_bones]
        self.affect_bones(context)
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
        if isinstance(active_bone, PoseBone):
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
        if isinstance(active_bone, PoseBone):
            active_bone = active_bone.bone
        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        if all([b.parent == active_bone for rig, b in bone_tuples_to_parent]):
            cls.poll_message_set("Selected bones are already parented to the active one.")
            return False
        return True

    def parent_edit_bones(self, parent_eb: EditBone, bone_tuples_to_parent: list[tuple[Object, EditBone]]):
        parent_eb.hide = False
        for rig, child_eb in bone_tuples_to_parent:
            self.parent_edit_bone(parent_eb, child_eb)

    def parent_edit_bone(self, parent_eb: EditBone, child_eb: EditBone):
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

    def affect_ebones(self, context, ebones: list[EditBone]) -> set[str]:
        rig = active_rig(context)
        parent = get_active_bone(context)
        parent_name = parent.name

        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        self.parent_edit_bones(parent, bone_tuples_to_parent)
        affected_bones_names = {t[1].name for t in bone_tuples_to_parent}

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
                affected_bones_names |= set([t[1].name for t in flipped_bone_tuples_to_parent])

        plural = "s" if len(bone_tuples_to_parent) != 1 else ""
        message = (f'Parented {len(bone_tuples_to_parent)} bone{plural} to "{parent_name}".')
        if rig.data.use_mirror_x and flipped_bone_tuples_to_parent:
            message += "(Symmetrized!)"
        self.report(
            {'INFO'},
            message,
        )
        return affected_bones_names


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
        if isinstance(active_bone, PoseBone):
            active_bone = active_bone.bone
        bone_tuples_to_parent = get_selected_bone_tuples(context, exclude_active=True)
        if all([b.parent == active_bone and b.use_connect for rig, b in bone_tuples_to_parent]):
            cls.poll_message_set("Selected bones are already parented and connected to the active one.")
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
        rig = active_rig(context)
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

        self.report(
            {'INFO'},
            "Parented {num_objects} objects to {num_bones} bones."
            .format(num_objects=len(target_objs), num_bones=len(pbones))
        )
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
    bl_label = iface_("Bone Parenting")

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
        pie.operator('pose.separate_selected_bones', text="Separate Selected", icon='UNLINKED')

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
            hotkey_kwargs={
                'type': "P",
                'value': "PRESS"
            },
            keymap_name=keymap_name,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_bone_parenting'},
        )
