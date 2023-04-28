import bpy
from bpy.types import Menu, Constraint, PoseBone, UILayout
from typing import List, Tuple
from ..generation import naming
from ..generation.cloudrig import register_hotkey

def get_constraint_icon(constraint: Constraint) -> str:
    """We do not ask questions about this function. We accept it."""
    if constraint.type == 'ACTION':
        return 'ACTION'

    icons = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys()
    return icons[bpy.types.UILayout.icon(constraint)-48]

def get_constrained_bones(pose_bone: PoseBone) -> List[Tuple[Constraint, str]]:
    entries = []
    rig = pose_bone.id_data
    for pb in rig.pose.bones:
        for con in pb.constraints:
            if (
                hasattr(con, 'target')
                and hasattr(con, 'subtarget')
                and con.target == rig
                and con.subtarget 
                and con.subtarget == pose_bone.name
            ):
                entries.append((con, pb.name))
                break

            if con.type == 'ARMATURE':
                for t in con.targets:
                    if (
                        t.target == rig
                        and t.subtarget == pose_bone.name
                    ):
                        entries.append((con, pb.name))
    
    return entries

def get_target_bones(pose_bone: PoseBone) -> List[Tuple[Constraint, str]]:
    rig = pose_bone.id_data
    entries = []
    for con in pose_bone.constraints:
        if con.type == 'ARMATURE':
            for t in con.targets:
                if (
                    t.target == rig
                    and t.subtarget
                    and t.subtarget in rig.data.bones
                ):
                    entries.append((con, t.subtarget))

        if (
            hasattr(con, 'subtarget')
            and con.target == rig
            and con.subtarget
            and con.subtarget in rig.data.bones
        ):
            entries.append((con, con.subtarget))
    
    return entries


class POSE_MT_PIE_bone_constraint_targets(Menu):
    bl_label = "Constraint Targets"

    @staticmethod
    def draw_select_bone(layout: UILayout, con: Constraint, subtarget: str):
        icon = get_constraint_icon(con)
        op = layout.operator(
            'pose.select_bone_by_name', 
            text=con.name + ": " + subtarget,
            icon=icon
        )
        op.bone_name = subtarget

    def draw(self, context):
        layout = self.layout
        active_pb = context.active_pose_bone

        entries = get_target_bones(active_pb)

        for con, subtarget in entries:
            self.draw_select_bone(layout, con, subtarget)


class POSE_MT_PIE_constrained_bones(Menu):
    bl_label = "Constrained Bones"

    @staticmethod
    def draw_select_bone(layout: UILayout, con: Constraint, bone_name: str):
        icon = get_constraint_icon(con)
        op = layout.operator(
            'pose.select_bone_by_name', 
            text=f"{bone_name} ({con.name})", 
            icon=icon
        )
        op.bone_name = bone_name

    def draw(self, context):
        layout = self.layout
        active_pb = context.active_pose_bone

        entries = get_constrained_bones(active_pb)

        for con, bone_name in entries:
            self.draw_select_bone(layout, con, bone_name)


class POSE_MT_PIE_child_bones(Menu):
    bl_label = "Child Bones"

    def draw(self, context):
        layout = self.layout
        active_bone = context.active_bone or context.active_pose_bone

        for child_pb in active_bone.children:
            op = layout.operator('pose.select_bone_by_name', text=child_pb.name, icon='BONE_DATA')
            op.bone_name = child_pb.name


class CLOUDRIG_PIE_select_bone(Menu):
    bl_label = "Select Bone"

    @classmethod
    def poll(cls, context):
        rig = context.pose_object or context.object
        if not rig or rig.type != 'ARMATURE':
            return False

        active_bone = context.active_bone or context.active_pose_bone
        if not active_bone:
            return False

        active_pose_bone = rig.pose.bones.get(active_bone.name)
        if not active_pose_bone:
            return False

        return True

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.object
        active_bone = context.active_bone or context.active_pose_bone
        active_pb = rig.pose.bones.get(active_bone.name)

        pie = layout.menu_pie()

        # 1) Parent Bone.
        if active_pb.parent:
            op = pie.operator('pose.select_parent_bone', text="Parent: " + active_pb.parent.name, icon='BONE_DATA')
        else:
            pie.separator()

        # 2) Child Bone(s).
        if len(active_pb.children) == 1:
            child = active_pb.children[0]
            op = pie.operator('pose.select_bone_by_name', text="Child: "+child.name, icon='BONE_DATA')
            op.bone_name = child.name
        elif len(active_pb.children) > 1:
            pie.menu('POSE_MT_PIE_child_bones', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 3) Bone(s) targeted by this bone's constraints.
        target_bones = get_target_bones(active_pb)
        if len(target_bones) == 1:
            con, bone_name = target_bones[0]
            POSE_MT_PIE_bone_constraint_targets.draw_select_bone(pie, con, bone_name)
        elif len(target_bones) > 1:
            pie.menu('POSE_MT_PIE_bone_constraint_targets', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 4) Bone(s) with constraints that target this bone.
        constrained_bones = get_constrained_bones(active_pb)
        if len(constrained_bones) == 1:
            con, bone_name = constrained_bones[0]
            POSE_MT_PIE_constrained_bones.draw_select_bone(pie, con, bone_name)
        elif len(constrained_bones) > 1:
            pie.menu('POSE_MT_PIE_constrained_bones', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 5) Deform Bone.
        sliced = naming.slice_name(active_pb.name)
        new_name = naming.make_name(["DEF"], sliced[1], sliced[2])
        def_bone = rig.pose.bones.get(new_name)
        if def_bone and def_bone.name != active_pb.name:
            op = pie.operator('pose.select_bone_by_name_relation', text="Deform Bone: " + def_bone.name, icon='BONE_DATA')
            op.prefix="DEF"
        else:
            pie.separator()
        
        # 6) Empty.
        pie.separator()

        # 7) BBone Handle Start
        start = active_pb.bbone_custom_handle_start
        if start and start.name in rig.pose.bones:
            pie.operator('pose.select_bone_by_name', text="Start Handle: " + start.name, icon='OUTLINER_OB_CURVE')
        else:
            pie.separator()

        # 8) BBone Handle End
        end = active_pb.bbone_custom_handle_end
        if end and end.name in rig.pose.bones:
            pie.operator('pose.select_bone_by_name', text="End Handle: " + end.name, icon='OUTLINER_OB_CURVE')
        else:
            pie.separator()


registry = [
    POSE_MT_PIE_constrained_bones,
    POSE_MT_PIE_bone_constraint_targets,
    POSE_MT_PIE_child_bones,
    CLOUDRIG_PIE_select_bone
]

def register():
    for key_cat in {'Pose', 'Weight Paint', 'Armature'}:
        register_hotkey('wm.call_menu_pie',
            hotkey_kwargs = {'type': "D", 'value': "PRESS", 'alt': True},
            key_cat = key_cat,
            space_type = 'VIEW_3D',
            op_kwargs = {'name' : 'CLOUDRIG_PIE_select_bone'}
        )
