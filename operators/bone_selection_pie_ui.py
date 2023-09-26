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

def get_active_bone(context):
    rig = context.pose_object or context.active_object
    if not rig or rig.type != 'ARMATURE':
        return None

    active_bone = context.active_bone or context.active_pose_bone
    if not active_bone:
        return None

    active_pose_bone = rig.pose.bones.get(active_bone.name)
    if not active_pose_bone:
        return None

    return active_pose_bone or active_bone

class POSE_MT_PIE_bone_constraint_targets(Menu):
    bl_label = "Constraint Targets"

    @classmethod
    def poll(cls, context):
        return get_active_bone(context)

    @staticmethod
    def draw_select_bone(layout: UILayout, con: Constraint, subtarget: str, start_text=""):
        icon = get_constraint_icon(con)
        op = layout.operator(
            'pose.select_bone_by_name', 
            text=start_text + con.name + ": " + subtarget,
            icon=icon
        )
        op.bone_name = subtarget

    def draw(self, context):
        layout = self.layout
        active_pb = context.active_pose_bone or context.active_object.pose.bones.get(context.active_bone.name)

        entries = get_target_bones(active_pb)

        for con, subtarget in entries:
            self.draw_select_bone(layout, con, subtarget)


class POSE_MT_PIE_constrained_bones(Menu):
    bl_label = "Constrained Bones"

    @classmethod
    def poll(cls, context):
        return get_active_bone(context)

    @staticmethod
    def draw_select_bone(layout: UILayout, con: Constraint, bone_name: str, start_text=""):
        icon = get_constraint_icon(con)
        op = layout.operator(
            'pose.select_bone_by_name', 
            text=f"{start_text}{bone_name} ({con.name})", 
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

    @classmethod
    def poll(cls, context):
        return get_active_bone(context)

    def draw(self, context):
        layout = self.layout
        active_bone = context.active_bone or context.active_pose_bone

        for child_pb in active_bone.children:
            op = layout.operator('pose.select_bone_by_name', text=child_pb.name, icon='BONE_DATA')
            op.bone_name = child_pb.name


class CLOUDRIG_MT_PIE_select_bone(Menu):
    bl_label = "Select Bone"

    @classmethod
    def poll(cls, context):
        return get_active_bone(context)

    def draw(self, context):
        layout = self.layout
        rig = context.pose_object or context.active_object
        active_bone = context.active_bone or context.active_pose_bone
        active_pb = rig.pose.bones.get(active_bone.name)

        pie = layout.menu_pie()

        # 1) < Parent Bone.
        if active_bone.parent:
            op = pie.operator('pose.select_parent_bone', text="Parent: " + active_bone.parent.name, icon='BONE_DATA')
        else:
            pie.separator()

        # 2) > Child Bone(s).
        if len(active_bone.children) == 1:
            child = active_pb.children[0]
            if child:
                # Sometimes child can be none...? I don't get how.
                op = pie.operator('pose.select_bone_by_name', text="Child: "+child.name, icon='BONE_DATA')
                op.bone_name = child.name
        elif len(active_bone.children) > 1:
            pie.menu('POSE_MT_PIE_child_bones', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 3) v Lower number bone
        lower_bone = rig.pose.bones.get(naming.increment_name(active_bone.name, increment=-1))
        if not lower_bone and active_bone.name.startswith("STR"):
            # TODO: Should probably change the bone naming of CloudRig, to remove the TIP- suffix, and just increment the bone name instead.
            prev_name = active_bone.name.replace("STR-TIP", "STR")
            lower_bone = rig.pose.bones.get(prev_name)
            op = pie.operator('pose.select_bone_by_name', text=lower_bone.name, icon='TRIA_DOWN')
            op.bone_name = prev_name
        elif lower_bone:
            op = pie.operator('pose.select_bone_by_name', text=lower_bone.name, icon='TRIA_DOWN')
            op.bone_name = lower_bone.name
        else:
            pie.separator()

        # 4) ^ Higher number bone
        higher_bone = rig.pose.bones.get(naming.increment_name(active_bone.name, increment=1))
        if not higher_bone and active_bone.name.startswith("STR"):
            # TODO: Should probably change the bone naming of CloudRig, to remove the TIP- suffix, and just increment the bone name instead.
            tip_name = active_bone.name.replace("STR", "STR-TIP")
            higher_bone = rig.pose.bones.get(tip_name)
            if higher_bone:
                op = pie.operator('pose.select_bone_by_name', text=higher_bone.name, icon='TRIA_UP')
                op.bone_name = tip_name
        elif higher_bone:
            op = pie.operator('pose.select_bone_by_name', text=higher_bone.name, icon='TRIA_UP')
            op.bone_name = higher_bone.name
        else:
            pie.separator()

        # 5) ^> Bone(s) with constraints that target this bone.
        constrained_bones = get_constrained_bones(active_pb)
        if len(constrained_bones) == 1:
            con, bone_name = constrained_bones[0]
            POSE_MT_PIE_constrained_bones.draw_select_bone(pie, con, bone_name, start_text="Constrained Bone: ")
        elif len(constrained_bones) > 1:
            pie.menu('POSE_MT_PIE_constrained_bones', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 6) <^ Bone(s) targeted by this bone's constraints.
        target_bones = get_target_bones(active_pb)
        if len(target_bones) == 1:
            con, bone_name = target_bones[0]
            POSE_MT_PIE_bone_constraint_targets.draw_select_bone(pie, con, bone_name, start_text="Constraint Target: ")
        elif len(target_bones) > 1:
            pie.menu('POSE_MT_PIE_bone_constraint_targets', icon='COLLAPSEMENU')
        else:
            pie.separator()

        # 7) <v BBone Handle Start & End <OR> Corresponding Deform Bone.
        start = active_bone.bbone_custom_handle_start
        end = active_bone.bbone_custom_handle_end

        sliced = naming.slice_name(active_bone.name)
        new_name = naming.make_name(["DEF"], sliced[1], sliced[2])
        def_bone = rig.pose.bones.get(new_name)
        if start or end:
            col = pie.column()
            if start:
                op = col.operator('pose.select_bone_by_name', text="Start Handle: " + start.name, icon='OUTLINER_OB_CURVE')
                op.bone_name = start.name
            if end:
                op = col.operator('pose.select_bone_by_name', text="End Handle: " + end.name, icon='OUTLINER_OB_CURVE')
                op.bone_name = end.name
        elif def_bone and def_bone.name != active_bone.name:
            op = pie.operator('pose.select_bone_by_name_relation', text="Deform Bone: " + def_bone.name, icon='BONE_DATA')
            op.prefix="DEF"
        else:
            pie.separator()

        # 8) v> Search bone.
        pie.operator('bone.select_by_name_search', icon='VIEWZOOM')

registry = [
    POSE_MT_PIE_constrained_bones,
    POSE_MT_PIE_bone_constraint_targets,
    POSE_MT_PIE_child_bones,
    CLOUDRIG_MT_PIE_select_bone
]

def register():
    for key_cat in {'Pose', 'Weight Paint', 'Armature'}:
        register_hotkey('wm.call_menu_pie',
            hotkey_kwargs = {'type': "D", 'value': "PRESS", 'alt': True},
            key_cat = key_cat,
            space_type = 'VIEW_3D',
            op_kwargs = {'name' : 'CLOUDRIG_MT_PIE_select_bone'}
        )
