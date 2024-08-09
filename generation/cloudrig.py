# SPDX-License-Identifier: GPL-2.0-or-later

"""
This file is loaded into a self-executing text datablock and attached to all
CloudRig rigs.
It's responsible for drawing the CloudRig panel in the 3D View's Sidebar.
"""

import bpy, json, ast, re, contextlib
from collections import OrderedDict, defaultdict
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
    IntProperty,
    CollectionProperty,
)
from bpy.types import (
    bpy_struct,
    ID,
    Object,
    PoseBone,
    UILayout,
    UIList,
    Panel,
    Menu,
    Operator,
    PropertyGroup,
    BoneCollection,
)
from rna_prop_ui import rna_idprop_value_item_type
from bpy.utils import register_class, unregister_class

from mathutils import Matrix, Vector
from math import acos, pi
from bl_ui.generic_ui_list import draw_ui_list

cloudrig_addon = False
if __package__ and "CloudRig" in __package__:
    cloudrig_addon = True

if cloudrig_addon:
    from .. import icons


#######################################
############ Context Checks ###########
#######################################


def is_active_cloudrig(context) -> Object | bool:
    """If the active object is a cloudrig, return it."""
    if not hasattr(context, 'pose_object'):
        # Can happen when a file is saved with the UI open,
        # and that UI is trying to draw during file open, when context isn't
        # initialized yet.
        return False
    rig = context.pose_object or context.active_object
    if not rig:
        return False
    if rig.type != 'ARMATURE':
        return False
    if rig and is_generated_cloudrig(rig):
        return rig
    return False


def is_generated_cloudrig(obj: Object) -> bool:
    """Return whether obj is a rig marked as being compatible with cloudrig.py."""
    return (
        obj
        and obj.type == 'ARMATURE'
        and 'is_generated_cloudrig' in obj.data
        and obj.data['is_generated_cloudrig']
    )


def is_active_cloud_metarig(context) -> bool:
    return is_cloud_metarig(context.active_object)


def is_cloud_metarig(obj: Object) -> bool:
    return (
        obj
        and obj.type == 'ARMATURE'
        and hasattr(obj, 'cloudrig')
        and obj.cloudrig.enabled
    )


def find_metarig_of_rig(context, rig: Object) -> Object | None:
    # First, try to find it by name, which should work most of the time.
    for prefix in {'RIG-', 'FAILED-RIG-'}:
        if rig.name.startswith(prefix):
            metarig = context.scene.objects.get(rig.name.replace(prefix, ""))
            if not metarig:
                metarig = context.scene.objects.get(rig.name.replace(prefix, "META-"))

            if (
                metarig
                and metarig.cloudrig.generator.target_rig
                and metarig.cloudrig.generator.target_rig != rig
            ):
                # Edge case: The names match, but this metarig is targetting another rig.
                # In this case, don't match the metarig.
                metarig = None

            if metarig:
                return metarig

    # If that failed, scan the whole scene.
    for obj in context.scene.objects:
        if obj.type != 'ARMATURE':
            continue
        if obj.cloudrig.generator.target_rig == rig:
            return obj


def find_cloudrig(
    context, *, allow_metarigs=True, filter_func: callable = None
) -> Object | None:
    """Find the CloudRig metarig or generated rig most relevant to the current context.
    For example, if the active object is a mesh which is deformed by a generated rig, return that generated rig.
    """

    def is_good_rig(rig):
        return rig and (
            is_generated_cloudrig(rig) or (allow_metarigs and is_cloud_metarig(rig))
        )

    if not filter_func:
        filter_func = is_good_rig

    active = context.active_object
    if filter_func(active):
        return active

    if active and active.parent and filter_func(active.parent):
        return active.parent

    pose_ob = context.pose_object
    if filter_func(pose_ob):
        return pose_ob

    if active and active.type == 'MESH':
        return get_cloudrig_of_mesh(active)[0]


def get_cloudrig_of_mesh(meshob: Object) -> tuple[Object | None, str | None]:
    """If this mesh is being deformed by a CloudRig rig, return it, and the name of the modifier."""
    return get_deforming_armature(meshob, is_generated_cloudrig)


def get_deforming_armature(meshob: Object, filter_func=lambda o: True):
    for m in meshob.modifiers:
        if m.type == 'ARMATURE' and m.object and (filter_func(m.object)):
            return m.object, m.name
    return None, None


def poll_cloudrig_operator(operator, context, modes={}, **kwargs):
    if modes and context.mode not in modes:
        operator.poll_message_set(f"Must be in mode: {modes}")
        return False
    rig = find_cloudrig(context, **kwargs)
    if not rig:
        operator.poll_message_set(
            "Could not find a CloudRig metarig or generated rig in this context."
        )
        return False
    return rig


class CloudRigOperator(Operator):
    """This class implements a basic draw function that just draws all the operator properties.
    This is necessary because of our hotkey system and UI.
    In order to avoid creating duplicate keymap entries, we insert a "hash" value in each keymap's
    operator properties. But normally, this "hash" value gets drawn in the redo panel, which we don't want.

    So, by letting every class inherit this draw function, we can fix that.
    """

    def draw(self, context):
        layout = self.layout
        props = type(self).__annotations__
        for prop in props:
            layout.prop(self, prop)


#######################################
########## Snapping & Baking ##########
#######################################


class SnappingOpMixin:
    bone_names: StringProperty(
        name="Bone Names",
        description="A python list converted to a string with json.dumps(). The order of the bone names matters, as dependents should come after their dependencies (ie. children after parents)",
    )
    prop_bone: StringProperty(
        name="Property Bone Name",
        description="Name of the pose bone on the active object that should have a custom property named prop_id",
    )
    prop_id: StringProperty(
        name="Custom Property Name",
        description="Name of the custom property on the pose bone, which will be toggled by this operator",
    )

    @classmethod
    def poll(cls, context) -> bool:
        rig = poll_cloudrig_operator(cls, context, modes={'POSE'})
        if not rig:
            return False
        return True

    @staticmethod
    def get_prop_target_value(prop_pb, prop_id) -> float:
        if prop_pb[prop_id] < 1.0:
            return 1.0
        return 0.0

    def get_properties_bone(self, rig: Object) -> PoseBone:
        if self.prop_bone not in rig.pose.bones:
            raise Exception(f"Bone not found in rig: `{self.prop_bone}`.")

        prop_pb = rig.pose.bones[self.prop_bone]
        if self.prop_id not in prop_pb:
            raise Exception(
                f"Property `{self.prop_id}` not found in bone `{self.prop_bone}`."
            )

        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        if int(prop_pb[self.prop_id]) == target_value:
            raise Exception(
                f"Value of property `{self.prop_id}` is already {target_value}."
            )

        return prop_pb

    def get_affected_pbones(self, rig: Object) -> set[PoseBone]:
        affected_pbones = set()
        for bone_name in ast.literal_eval(self.bone_names):
            pb = rig.pose.bones.get(bone_name)
            if pb:
                affected_pbones.add(pb)
            else:
                raise Exception(f"Bone `{bone_name}` not found.")
        return affected_pbones

    @staticmethod
    def get_pbone_matrix_map(
        bones_to_snap: list[PoseBone], snap_to_bones: list[PoseBone] = []
    ) -> OrderedDict[str, Matrix]:
        if not snap_to_bones:
            snap_to_bones = bones_to_snap
        assert len(bones_to_snap) == len(snap_to_bones)
        return OrderedDict(
            [
                (snapped_bone.name, snap_target.matrix.copy())
                for snapped_bone, snap_target in zip(bones_to_snap, snap_to_bones)
            ]
        )

    def set_bone_selection(self, rig, select=False, pbones: list[PoseBone] = None):
        if not pbones:
            pbones = rig.pose.bones
        for pb in pbones:
            pb.bone.select = select

    @staticmethod
    def reveal_bones(pbones: list[PoseBone]):
        for pb in pbones:
            if pb.bone.hide:
                pb.bone.hide = False
            if not any([coll.is_visible for coll in pb.bone.collections]):
                coll = pb.bone.collections[0]
                while coll:
                    coll.is_visible = True
                    coll = coll.parent

    def set_bone_matrices(
        self, context, rig: Object, pbone_matrix_map: dict[str, Matrix]
    ):
        for bone_name, mat in pbone_matrix_map.items():
            pb = rig.pose.bones[bone_name]
            pb.matrix = mat.copy()
            context.view_layer.update()
            pb.matrix = mat.copy()


class SnapBakeOpMixin(SnappingOpMixin):
    do_bake: BoolProperty(name="Bake", default=False)
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")
    key_before_start: BoolProperty(
        name="Key Before Start",
        description="Insert a keyframe of the original values one frame before the bake range. This is to avoid undesired interpolation towards the bake",
    )
    key_after_end: BoolProperty(
        name="Key After End",
        description="Insert a keyframe of the original values one frame after the bake range. This is to avoid undesired interpolation after the bake",
    )

    def invoke(self, context, _event):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        self.do_bake = False
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout

        self.layout.prop(self, 'do_bake')
        split = layout.split(factor=0.1)
        split.row()
        col = split.column()
        if self.do_bake:
            time_row = col.row(align=True)
            time_row.prop(self, 'frame_start')
            time_row.prop(self, 'frame_end')
            fix_row = col.row(align=True)
            fix_row.prop(self, 'key_before_start')
            fix_row.prop(self, 'key_after_end')

        self.draw_affected_bones(layout, context)

    def draw_affected_bones(self, layout, context):
        rig = find_cloudrig(context)
        if not rig:
            return
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def get_frame_range(self, context) -> list[int]:
        if not self.do_bake:
            return [context.scene.frame_current]

        return list(range(self.frame_start, self.frame_end + 1))

    @staticmethod
    def ensure_action(rig: Object):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.action = bpy.data.actions.new("ACT-" + rig.name)

    def map_frames_to_bone_matrices(
        self,
        context,
        bones_to_snap: list[PoseBone],
        snap_to_bones: list[PoseBone] = [],
        frame_numbers: list[int] = [],
    ) -> OrderedDict[int, OrderedDict[PoseBone, Matrix]]:
        if not frame_numbers:
            frame_numbers = self.get_frame_range(context)
        if not snap_to_bones:
            snap_to_bones = bones_to_snap

        frame_matrix_map = OrderedDict()
        for frame_number in frame_numbers:
            frame_matrix_map[frame_number] = self.map_single_frame_to_bone_matrices(
                context, frame_number, bones_to_snap, snap_to_bones
            )

        return frame_matrix_map

    def map_single_frame_to_bone_matrices(
        self,
        context,
        frame_number: int,
        bones_to_snap: list[PoseBone],
        snap_to_bones: list[PoseBone] = [],
    ) -> OrderedDict[str, Matrix]:
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        return self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

    def keyframe_bones(
        self,
        context,
        rig: Object,
        frame_matrix_map: OrderedDict[int, OrderedDict[str, Matrix]],
        prop_pb: PoseBone,
    ):
        pbones = [
            rig.pose.bones[name]
            for name in list(list(frame_matrix_map.values())[0].keys())
        ]

        # Deselect all bones, then reveal and select affected bones.
        self.set_bone_selection(rig, False)
        self.reveal_bones(pbones)
        self.set_bone_selection(rig, True, pbones)

        frame_numbers = list(frame_matrix_map.keys())

        if self.key_before_start:
            # Key original value and transforms one frame before the selected bake range.
            # This is to avoid our bake causing undesired interpolation before the bake range.
            context.scene.frame_set(frame_numbers[0] - 1)
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)
            bpy.ops.anim.keyframe_insert()

        if self.key_after_end:
            # Key original value and transforms one frame after the selected bake range.
            context.scene.frame_set(frame_numbers[-1] + 1)
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)
            bpy.ops.anim.keyframe_insert()

        # ViewLayer Update is necessary for some reason.
        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        # Idk why we have to go over them twice, but if we don't, we get issues
        # at the start and end of the frame range.
        for i in range(2):
            for frame_number, pbone_matrix_map in frame_matrix_map.items():
                context.scene.frame_set(frame_number)

                # Change & key property value.
                prop_pb[self.prop_id] = target_value
                prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)

                self.set_bone_matrices(context, rig, pbone_matrix_map)
                bpy.ops.anim.keyframe_insert()


class POSE_OT_cloudrig_snap_bake(SnapBakeOpMixin, CloudRigOperator):
    "Flip a custom property's value while preserving the world-matrix " "of some bones"
    bl_idname = 'pose.cloudrig_snap_bake'
    bl_label = "Snap & Bake Bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        return self.execute_bone_snap_bake(context)

    def execute_bone_snap_bake(self, context) -> set:
        rig = find_cloudrig(context)
        if not rig:
            return {'CANCELLED'}
        try:
            prop_pb = self.get_properties_bone(rig)
            affected_pbones = self.get_affected_pbones(rig)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        active_frame_bkp = context.scene.frame_current

        # Save the matrix of each bone at each frame.
        frame_matrix_map = self.map_frames_to_bone_matrices(context, affected_pbones)

        if self.do_bake:
            self.ensure_action(rig)
            self.keyframe_bones(context, rig, frame_matrix_map, prop_pb)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Store (copies!) of world matrices.
        pbone_matrix_map = list(frame_matrix_map.values())[0]

        # Deselect all bones.
        self.set_bone_selection(rig, False)
        # Reveal & select affected bones.
        self.reveal_bones(affected_pbones)
        self.set_bone_selection(rig, True, affected_pbones)

        # Change property value.
        target_value = self.get_prop_target_value(prop_pb, self.prop_id)
        prop_pb[self.prop_id] = target_value
        # Restore world matrices.
        self.set_bone_matrices(context, rig, pbone_matrix_map)

        # If property value is no longer what it should be, change it again,
        # and this time keyframe it.
        if prop_pb[self.prop_id] != target_value:
            # This happens when the property was already keyed, and the depsgraph update
            # caused it to reset to the previously keyed value.
            prop_pb[self.prop_id] = target_value
            prop_pb.keyframe_insert(f'["{self.prop_id}"]', group=prop_pb.name)

        context.scene.frame_set(active_frame_bkp)
        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}


class POSE_OT_cloudrig_switch_parent_bake(POSE_OT_cloudrig_snap_bake, CloudRigOperator):
    "Change the parent while preserving the world-matrix of the affected " "bones, even in a frame range"

    bl_idname = 'pose.cloudrig_switch_parent_bake'
    bl_label = "Switch Parents & Preserve Transforms"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    parent_names: StringProperty(name="Parent Names")

    def parent_items(self, context):
        parents = ast.literal_eval(self.parent_names)
        items = [(str(i), name, name) for i, name in enumerate(parents)]
        return items

    selected: EnumProperty(name="Selected Parent", items=parent_items)

    def draw(self, context):
        self.layout.prop(self, 'selected', text='')
        super().draw(context)

    def get_prop_target_value(self, prop_pb, prop_id) -> int:
        return int(self.selected)


class POSE_OT_cloudrig_toggle_ikfk_bake(SnapBakeOpMixin, CloudRigOperator):
    "Toggle the rig component between IK and FK modes. Snap the affected" "bones so you can continue animating. Can also snap & bake the affected" "bones over a frame range"

    bl_idname = 'pose.cloudrig_toggle_ikfk_bake'
    bl_label = "Snap & Bake Bones to Other Bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    map_fk_to_ik: StringProperty(
        description="List of tuples of (fk_bone, target_bone) for snapping FK to IK"
    )
    map_ik_to_fk: StringProperty(
        description="List of tuples of (ik_bone, target_bone) for snapping IK to FK"
    )
    ik_pole: StringProperty(
        description="Name of IK pole vector bone, for snapping IK to FK"
    )
    ik_first: StringProperty(
        description="Name of the first bone in the IK chain. Necessary for IK pole snapping logic"
    )
    fk_first: StringProperty(
        description="Name of the first bone in the FK chain. Necessary for IK pole snapping logic"
    )

    def invoke(self, context, _event):
        self.rig = context.active_object
        self.prop_pb = self.get_properties_bone(self.rig)
        self.current_value = self.prop_pb[self.prop_id]
        self.target_value = self.get_prop_target_value(self.prop_pb, self.prop_id)
        self.bone_map = self.get_bone_map(self.current_value)
        return super().invoke(context, _event)

    def execute(self, context):
        rig = context.active_object
        active_frame_bkp = context.scene.frame_current

        # Store (copies!) of world matrices.
        bones_to_snap = [self.rig.pose.bones[name] for name in self.bone_map.keys()]
        snap_to_bones = [self.rig.pose.bones[name] for name in self.bone_map.values()]
        frame_matrix_map = self.map_frames_to_bone_matrices(
            context, bones_to_snap, snap_to_bones
        )

        self.ik_last = bones_to_snap[0]
        if self.do_bake:
            self.keyframe_bones(context, rig, frame_matrix_map, self.prop_pb)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
            return {'FINISHED'}

        # Change property value.
        self.prop_pb[self.prop_id] = self.get_prop_target_value(
            self.prop_pb, self.prop_id
        )

        # Deselect all bones.
        self.set_bone_selection(self.rig, False)

        pbone_matrix_map = list(frame_matrix_map.values())[0]
        # Restore world matrices.
        self.set_bone_matrices(context, self.rig, pbone_matrix_map)

        if self.target_value == 1 and self.ik_pole:
            self.snap_pole_target()

        # Reveal & select affected bones.
        self.reveal_bones(bones_to_snap)
        self.set_bone_selection(self.rig, True, bones_to_snap)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def set_bone_selection(self, rig, select=False, pbones: list[PoseBone] = None):
        """Overrides SnapBakeOpMixin to also select the IK pole before keying."""
        print("PBONES:", pbones, select)
        if select and self.target_value == 1 and self.ik_pole:
            pbones.append(rig.pose.bones[self.ik_pole])
        super().set_bone_selection(rig, select, pbones)

    def set_bone_matrices(
        self, context, rig: Object, pbone_matrix_map: dict[str, Matrix]
    ):
        """Overrides SnapBakeOpMixin."""
        super().set_bone_matrices(context, rig, pbone_matrix_map)
        if self.target_value == 1 and self.ik_pole:
            self.snap_pole_target()

    def snap_pole_target(self) -> Matrix:
        """Snap the pole target based on the first IK bone.
        This needs to run after the IK wrist control had already been snapped.
        It's not perfect, but to make this work as best as possible, ensure:
            - IK chain lies flat on a plane (Else, Generator Log warns you.)
            - FK and IK rolls match perfectly. (Generator makes sure.)
            - FK elbow has Y/Z rotation locked. (See "limit_elbow_axes" param.)
        """

        # CloudRig's IK pole snapping is based on code by revolt_randy:
        # https://blenderartists.org/t/what-is-the-best-way-to-do-fk-ik-snapping/1427362/30
        # Which was based on code by Nathan Vegdahl aka Cessen:
        # https://blenderartists.org/t/visual-transform-helper-functions-for-2-5/500965

        def perpendicular_vector(v):
            """Returns a vector that is perpendicular to the one given.
            The returned vector is _not_ guaranteed to be normalized.
            """
            # Create a vector that is not aligned with v.
            # It doesn't matter what vector.  Just any vector
            # that's guaranteed to not be pointing in the same
            # direction.
            if abs(v[0]) < abs(v[1]):
                tv = Vector((1, 0, 0))
            else:
                tv = Vector((0, 1, 0))

            # Use cross prouct to generate a vector perpendicular to
            # both tv and (more importantly) v.
            return v.cross(tv)

        def rotation_difference(mat1, mat2):
            """Returns the shortest-path rotational difference between two
            matrices.
            """
            q1 = mat1.to_quaternion()
            q2 = mat2.to_quaternion()
            angle = acos(min(1, max(-1, q1.dot(q2)))) * 2
            if angle > pi:
                angle = -angle + (2 * pi)
            return angle

        def get_pose_matrix_in_other_space(mat, pose_bone):
            """Returns the transform matrix relative to pose_bone's current
            transform space.  In other words, presuming that mat is in
            armature space, slapping the returned matrix onto pose_bone
            should give it the armature-space transforms of mat.
            """
            return pose_bone.id_data.convert_space(
                matrix=mat, pose_bone=pose_bone, from_space='POSE', to_space='LOCAL'
            )

        def set_pose_translation(pose_bone, mat):
            """Sets the pose bone's translation to the same translation as the given matrix.
            Matrix should be given in bone's local space.
            """
            pose_bone.location = mat.to_translation()

        def match_pole_target(ik_first, ik_last, pole, match_bone):
            """Places an IK chain's pole target to match ik_first's
            transforms to match_bone.  All bones should be given as pose bones.
            You need to be in pose mode on the relevant armature object.
            ik_first: first bone in the IK chain
            ik_last:  last bone in the IK chain
            pole:  pole target bone for the IK chain
            match_bone:  bone to match ik_first to (probably first bone in a matching FK chain)
            length:  distance pole target should be placed from the chain center
            """
            a = ik_first.matrix.to_translation()
            b = ik_last.matrix.to_translation() + ik_last.vector

            # Vector from the head of ik_first to the
            # tip of ik_last
            ikv = b - a

            length = ik_first.length + match_bone.length

            # Get a vector perpendicular to ikv
            pv = perpendicular_vector(ikv).normalized() * length

            def set_pole(pvi):
                """Set pole target's position based on a vector
                from the arm center line.
                """
                # Translate pvi into armature space
                ploc = a + (ikv / 2) + pvi

                # Set pole target to location
                mat = get_pose_matrix_in_other_space(Matrix.Translation(ploc), pole)
                set_pose_translation(pole, mat)

                bpy.context.view_layer.update()

            set_pole(pv)

            # Get the rotation difference between ik_first and match_bone
            angle = rotation_difference(ik_first.matrix, match_bone.matrix)

            # Try compensating for the rotation difference in both directions
            pv1 = Matrix.Rotation(angle, 4, ikv) @ pv
            set_pole(pv1)
            ang1 = rotation_difference(ik_first.matrix, match_bone.matrix)

            pv2 = Matrix.Rotation(-angle, 4, ikv) @ pv
            set_pole(pv2)
            ang2 = rotation_difference(ik_first.matrix, match_bone.matrix)

            # Do the one with the smaller angle
            if ang1 < ang2:
                set_pole(pv1)

        ik_pole = self.rig.pose.bones[self.ik_pole]
        fk_first = self.rig.pose.bones[self.fk_first]
        ik_first = self.rig.pose.bones[self.ik_first]
        match_pole_target(ik_first, self.ik_last, ik_pole, fk_first)
        return ik_pole.matrix

    def map_single_frame_to_bone_matrices(
        self, context, frame_number, bones_to_snap, snap_to_bones
    ):
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        pbone_matrix_map = self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

        return pbone_matrix_map

    def get_bone_map(self, ik_value: float) -> OrderedDict[str, str]:
        map_fk_to_ik = OrderedDict(ast.literal_eval(self.map_fk_to_ik))
        map_ik_to_fk = OrderedDict(ast.literal_eval(self.map_ik_to_fk))

        bone_map = map_fk_to_ik if ik_value == 1 else map_ik_to_fk

        return bone_map

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Snapped bones:")
        for from_bone, to_bone in self.bone_map.items():
            bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")

        if self.current_value < 1:
            bone_column.label(text=f"{' '*10} {self.ik_pole}")


#######################################
######## Convenience Operators ########
#######################################


class POSE_OT_cloudrig_keyframe_all_settings(CloudRigOperator):
    """Keyframe all rig settings that are being drawn in the below UI"""

    bl_idname = 'pose.cloudrig_keyframe_all_settings'
    bl_label = "Keyframe CloudRig Settings"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        rig = poll_cloudrig_operator(cls, context, allow_metarigs=False)
        if not rig:
            return False
        if 'ui_data' not in rig.data:
            cls.poll_message_set("CloudRig armature lacks any UI data.")
            return False
        return True

    def execute(self, context):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return

        props_to_key: list[tuple[ID | PoseBone, str]] = []

        def add_props_to_key_recursive(ui_data: OrderedDict | list):
            if hasattr(ui_data, 'items'):
                elem_list = [data for _name, data in ui_data.items()]
            elif type(ui_data) == list:
                elem_list = ui_data

            for elem_data in elem_list:
                if type(elem_data) == str:
                    continue
                if 'owner_path' in elem_data:
                    # This is a property, so it can be keyed.
                    try:
                        owner = rig.path_resolve(elem_data['owner_path'])
                        if not owner:
                            continue
                    except ValueError:
                        # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
                        continue

                    if type(owner) == BoneCollection:
                        # Let's not keyframe bone visibilities.
                        continue

                    prop_name = elem_data['prop_name']
                    props_to_key.append((owner, prop_name))

                add_props_to_key_recursive(elem_data)

        add_props_to_key_recursive(ui_data)

        for prop_owner, prop_name in props_to_key:
            try:
                prop_owner.keyframe_insert(prop_name, group=prop_owner.name)
            except TypeError:
                # Happens if property is not animatable.
                pass

        return {'FINISHED'}


class POSE_OT_cloudrig_reset(CloudRigOperator):
    """Reset all bone transforms and custom properties to their default values"""

    bl_idname = 'pose.cloudrig_reset'
    bl_label = "Reset Rig"
    bl_options = {'REGISTER', 'UNDO'}

    reset_transforms: BoolProperty(
        name="Transforms", default=True, description="Reset bone transforms"
    )
    reset_props: BoolProperty(
        name="Properties", default=True, description="Reset custom properties"
    )
    selection_only: BoolProperty(
        name="Selected Only",
        default=False,
        description="Affect selected bones rather than all bones",
    )

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        rig = find_cloudrig(context)
        pbones = rig.pose.bones
        if self.selection_only:
            pbones = context.selected_pose_bones

        reset_rig(
            rig,
            reset_transforms=self.reset_transforms,
            reset_props=self.reset_props,
            pbones=pbones,
        )

        return {'FINISHED'}


def reset_rig(rig, *, reset_transforms=True, reset_props=True, pbones=[]):
    if not pbones:
        pbones = rig.pose.bones
    for pb in pbones:
        if reset_transforms:
            pb.location = (0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.scale = (1, 1, 1)

        if not reset_props or len(pb.keys()) == 0:
            continue

        rna_properties = [
            prop.identifier for prop in pb.bl_rna.properties if prop.is_runtime
        ]

        # Reset custom property values to their default value
        for key in pb.keys():
            if key.startswith("$"):
                continue
            if key in rna_properties:
                continue  # Addon defined property.

            property_settings = None
            try:
                property_settings = pb.id_properties_ui(key)
                if not property_settings:
                    continue
                property_settings = property_settings.as_dict()
                if not 'default' in property_settings:
                    continue
            except TypeError:
                # Some properties don't support UI data, and so don't have a default value. (like addon PropertyGroups)
                pass

            if not property_settings:
                continue

            if type(pb[key]) not in (float, int, bool):
                continue
            pb[key] = property_settings['default']


#######################################
########### Dynamic Rig UI ############
#######################################


class CLOUDRIG_PT_base(Panel):
    """Base class for all CloudRig sidebar panels."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'CloudRig'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context)

    def draw(self, context):
        pass


class CLOUDRIG_PT_settings(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_settings"
    bl_label = "Settings"

    def draw(self, context):
        layout = self.layout
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return

        layout.operator(
            POSE_OT_cloudrig_keyframe_all_settings.bl_idname,
            text='Keyframe All Settings',
            icon='KEYFRAME_HLT',
        )
        layout.operator(POSE_OT_cloudrig_reset.bl_idname, icon='LOOP_BACK')
        if hasattr(rig, 'cloudrig') and rig.cloudrig.enabled:
            # If CloudRig add-on is enabled, and this is a metarig.
            layout.separator()
            layout.prop(rig.cloudrig, 'ui_edit_mode', icon='GREASEPENCIL')
            if rig.cloudrig.ui_edit_mode:
                if hasattr(bpy.ops.pose, 'cloudrig_add_property_to_ui'):
                    layout.operator('pose.cloudrig_add_property_to_ui', icon='ADD')
                if hasattr(bpy.ops.object, 'cloudrig_ui_element_add'):
                    layout.operator('object.cloudrig_ui_element_add', icon='ADD')
                else:
                    print("Why didn't the class register")

        if ui_data:
            for panel_name, panel_data in ui_data.items():
                if panel_name == "":
                    layout.separator()
                    for label_name, label_data in panel_data.items():
                        if type(label_data) == str:
                            # It's a flag, not a UI element...
                            continue
                        draw_rig_settings_per_label(
                            layout=layout,
                            rig=rig,
                            ui_path=[""],
                            panel_name="",
                            panel_data=panel_data,
                            label_name=label_name,
                            label_data=label_data,
                        )
                else:
                    sane_name = re.sub(r'\W+', '', panel_name)
                    full_name = "CLOUDRIG_PT_custom_" + sane_name.lower().replace(
                        " ", ""
                    )
                    header, body = layout.panel(full_name)
                    self.draw_panel_header(context, header, panel_name)
                    if body:
                        self.draw_panel_contents(context, body, panel_name)

    def draw_panel_header(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return
        panel_data = ui_data[panel_name]

        draw_drag_operator(rig, ui_data, panel_data, panel_name, [], layout)

        layout.label(text=panel_name)

    def draw_panel_contents(self, context, layout, panel_name):
        rig, ui_data = get_rig_and_ui(context)
        if not rig:
            return

        panel_data = ui_data.get(panel_name)
        if panel_data:
            """Panel data contains a list of tuples.
            The first entry of each tuple is a string telling us the type of UI element to draw.
            The second entry is the for drawiong the element. Can be str, list, or dict, depending on the type.
            """
            for label_name, label_data in panel_data.items():
                if type(label_data) == str:
                    # This is a flag, not a label.
                    continue
                draw_rig_settings_per_label(
                    layout=layout,
                    rig=rig,
                    ui_path=[panel_name],
                    panel_name=panel_name,
                    panel_data=panel_data,
                    label_name=label_name,
                    label_data=label_data,
                )


def read_rig_panels(obj) -> OrderedDict:
    """Return the rig's UI data as a nested OrderedDict."""

    def tuples_to_dict(tuples: list[tuple[str, list]]) -> OrderedDict:
        """Convert a nested list of (string, data) tuples to a nested OrderedDict."""
        ordered_dict = OrderedDict()
        for key, value in tuples:
            if key not in {'op_kwargs'}:
                if type(value) == dict:
                    # We also want to convert regular dicts to OrderedDict,
                    # especially because they might contain tuple-lists.
                    value = [(k, v) for k, v in value.items()]
                if type(value) == list:
                    value = tuples_to_dict(value)

            ordered_dict[key] = value
        return ordered_dict

    if 'ui_data' not in obj.data:
        return OrderedDict()
    panels = obj.data['ui_data'].to_dict()['panels']
    return tuples_to_dict(panels)


def write_rig_panels(obj, panels: OrderedDict):
    # Convert back to a list of tuples so Blender can store it without mangling it.

    def dict_to_tuples(ordered_dict: OrderedDict) -> list[tuple[str, list]]:
        """Convert a nested OrderedDict to a nested list of tuples."""
        tuples = []
        for key, value in ordered_dict.items():
            if type(value) in {dict, OrderedDict}:
                value = dict_to_tuples(value)
            tuples.append((key, value))
        return tuples

    # If we store it in a custom property as a list, each element gets
    # converted to a weird type by Blender.
    # So, just put it in a dictionary with a single 'panels' key.
    # Then it can easily be converted back to python, see read_rig_panels().
    panels = {'panels': dict_to_tuples(panels)}
    obj.data['ui_data'] = panels


def get_rig_and_ui(context) -> tuple[Object, OrderedDict] | tuple[None, None]:
    """Find the most relevant CloudRig in the context, return it and its UI."""
    rig = find_cloudrig(context)

    if not rig:
        return None, None

    return rig, read_rig_panels(rig)


def draw_rig_settings_per_label(
    layout: UILayout,
    rig: Object,
    ###
    ui_path: list[str],
    panel_name: str,
    panel_data: OrderedDict,
    label_name: str,
    label_data: OrderedDict,
):
    if label_name:
        row = layout.row()
        draw_drag_operator(rig, panel_data, label_data, label_name, ui_path, row)
        row.label(text=label_name)

    # We need to figure out and pass the parent value string for the edit button.
    parent_value = ""
    if 'children' in ui_path and ui_path[-2] == 'children':
        parent_value = ui_path[-1]

    ui_path += [label_name]

    for row_name, row_data in label_data.items():
        if type(row_data) == str:
            # It's a flag, not a UI element.
            continue
        column = layout
        sub_row = column.row(align=True)
        draw_drag_operator(rig, label_data, row_data, row_name, ui_path, sub_row)
        sub_row.separator()

        for slider_name, slider_data in row_data.items():
            if type(slider_data) == str:
                # It's a flag, not a UI element.
                continue
            if slider_data.get('owner_path') == None:
                # Currently, all UI elements must have a property, and therefore a path to the property owner.
                # Note though that this path is allowed to be an empty string.
                continue
            texts = slider_data.get('texts', [])
            if texts:
                if texts.startswith("["):
                    texts = ast.literal_eval(texts)
                else:
                    texts = [t.strip() for t in texts]
            draw_slider(
                rig=rig,
                column=column,
                sub_row=sub_row,
                ###
                owner_path=slider_data.get('owner_path'),
                prop_name=slider_data.get('prop_name'),
                ###
                ui_path=ui_path + [row_name, slider_name],
                panel_name=panel_name,
                label_name=label_name,
                row_name=row_name,
                slider_name=slider_name,
                ###
                texts=texts,
                icon_true=slider_data.get('icon_true', 'CHECKBOX_HLT'),
                icon_false=slider_data.get('icon_false', 'CHECKBOX_DEHLT'),
                operator=slider_data.get('operator'),
                op_icon=slider_data.get('op_icon'),
                op_kwargs=slider_data.get('op_kwargs'),
                children=slider_data.get('children'),
                parent_value=parent_value,
            )


def draw_slider(
    *,
    rig,
    column: UILayout,
    sub_row: UILayout,
    ###
    owner_path: str,
    prop_name: str,
    ###
    ui_path: list[str] = [],
    panel_name="",
    label_name="",
    row_name="",
    slider_name="",
    icon_true='CHECKBOX_HLT',
    icon_false='CHECKBOX_DEHLT',
    ###
    texts=[],
    operator="",
    op_icon='BLANK1',
    op_kwargs={},
    ###
    children={},
    parent_value="",
):

    if owner_path == "":
        owner = rig
    else:
        try:
            owner = rig.path_resolve(owner_path)
        except ValueError:
            # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
            owner = None
            pass

    prop_value = None
    if not owner:
        sub_row.alert = True
        sub_row.label(
            text=f"Missing property owner: '{owner_path}' for property '{prop_name}'.",
            icon='ERROR',
        )
    else:
        try:
            prop_value = owner.path_resolve(prop_name)
        except ValueError:
            sub_row.alert = True
            sub_row.label(
                text=f"Missing property '{prop_name}' of owner '{owner_path}'.",
                icon='ERROR',
            )

    if not sub_row.alert:
        draw_property(
            layout=sub_row,
            prop_owner=owner,
            prop_name=prop_name,
            slider_name=slider_name,
            icon_true=icon_true,
            icon_false=icon_false,
            texts=texts,
        )
        if operator:
            draw_operator(
                sub_row, bl_idname=operator, op_icon=op_icon, op_kwargs=op_kwargs
            )

        prop_value_str = str(prop_value)
        if children:
            box_col = None
            for comma_separated_values, child_data in children.items():
                prop_values_as_str = [
                    v.strip() for v in comma_separated_values.split(",")
                ]
                if prop_value_str in prop_values_as_str:
                    for child_label_name, child_label_data in child_data.items():
                        if not box_col:
                            box_col = column.box().column()
                        draw_rig_settings_per_label(
                            layout=box_col,
                            rig=rig,
                            ui_path=ui_path + ['children', comma_separated_values],
                            panel_name=panel_name,
                            panel_data=child_data,
                            label_name=child_label_name,
                            label_data=child_label_data,
                        )

    if is_ui_edit_mode(rig):
        bracketless_prop_name = unquote_custom_prop_name(prop_name)

        if not sub_row.alert:
            if type(prop_value) in {int, bool}:
                child_op = sub_row.operator(
                    'pose.cloudrig_add_child_property_to_ui', icon='ADD', text=""
                )
                child_op.parent_value = prop_value_str
                child_op.parent_ui_path = json.dumps(ui_path)
                if type(owner) == PoseBone:
                    child_op.init_owner_path = f'pose.bones["{owner.name}"]'

            if (
                bracketless_prop_name not in owner.__dir__()
                and bracketless_prop_name in owner
            ):
                data_path = "active_object"
                if owner_path.startswith('['):
                    data_path += owner_path
                elif owner_path != "":
                    data_path += "." + owner_path
                # XXX: This doesn't work when the rig isn't the active object. We would need to pass context to check.
                edit_op = sub_row.operator(
                    "wm.properties_edit", text="", icon='PREFERENCES'
                )
                edit_op.data_path = data_path
                edit_op.property_name = bracketless_prop_name

        edit_op = sub_row.operator(
            'pose.cloudrig_edit_property_in_ui', text="", icon='GREASEPENCIL'
        )
        edit_op.init_owner_path = owner_path
        edit_op.prop_name = bracketless_prop_name
        ui_path_str = json.dumps(ui_path)
        edit_op.ui_path = ui_path_str
        if 'children' in ui_path:
            edit_op.parent_ui_path = json.dumps(ui_path[:-5])
            edit_op.parent_value = parent_value or ""
        else:
            edit_op.panel_name = panel_name
        edit_op.label_name = label_name
        edit_op.row_name = row_name
        edit_op.slider_name = slider_name
        if operator:
            edit_op.operator = operator
            edit_op.op_icon = op_icon
            edit_op.op_kwargs = json.dumps(op_kwargs)
        if children:
            edit_op.children = json.dumps(children)
        if texts:
            edit_op.texts = ", ".join(texts)
        if icon_true != 'CHECKBOX_HLT':
            edit_op.icon_true = icon_true
        if icon_false != 'CHECKBOX_DEHLT':
            edit_op.icon_false = icon_false
        sub_row.operator(
            'pose.cloudrig_remove_property_from_ui', text="", icon='X'
        ).ui_path = ui_path_str
    sub_row.separator()


def draw_property(
    layout: UILayout,
    prop_owner: bpy_struct,
    prop_name: str,
    *,
    slider_name="",
    icon_true="CHECKBOX_HLT",
    icon_false='CHECKBOX_DEHLT',
    texts=[],
):
    if not hasattr(prop_owner, 'path_resolve'):
        print("cloudrig.py: Cannot resolve path from: ", prop_owner)
        return
    prop_value = prop_owner.path_resolve(prop_name)

    bracketless_prop_name = unquote_custom_prop_name(prop_name)
    if not slider_name:
        slider_name = bracketless_prop_name

    value_type, is_array = rna_idprop_value_item_type(prop_value)

    if value_type is type(None) or issubclass(value_type, ID):
        # Property is a Datablock Pointer.
        layout.prop(prop_owner, prop_name, text=slider_name)
    elif value_type in {int, float, bool}:
        if texts and not is_array and len(texts) - 1 >= int(prop_value) >= 0:
            text = texts[int(prop_value)].strip()
            if text:
                slider_name += ": " + text
        if value_type == bool:
            icon = icon_true if prop_value else icon_false
            layout.prop(prop_owner, prop_name, toggle=True, text=slider_name, icon=icon)
        elif value_type in {int, float}:
            if bracketless_prop_name != prop_name:
                # If this is a custom property.

                # Property is a float/int/color
                # For large ranges, a slider doesn't make sense.
                try:
                    if bracketless_prop_name in prop_owner:
                        prop_settings = prop_owner.id_properties_ui(
                            bracketless_prop_name
                        ).as_dict()
                except TypeError:
                    # This happens for Python properties. There's no point drawing them.
                    return
                is_slider = (
                    not is_array
                    and prop_settings['soft_max'] - prop_settings['soft_min'] < 100
                )
                layout.prop(prop_owner, prop_name, slider=is_slider, text=slider_name)
            else:
                layout.prop(prop_owner, prop_name, text=slider_name)
    elif value_type == str:
        if (
            issubclass(type(prop_owner), bpy.types.Constraint)
            and prop_name == 'subtarget'
            and prop_owner.target
            and prop_owner.target.type == 'ARMATURE'
        ):
            # Special case for nice constraint sub-target selectors.
            layout.prop_search(prop_owner, prop_name, prop_owner.target.pose, 'bones')
        else:
            layout.prop(prop_owner, prop_name)
    else:
        layout.prop(prop_owner, prop_name, text=slider_name)


def draw_operator(
    layout: UILayout,
    bl_idname: str,
    op_icon='BLANK1',
    op_kwargs={},
    text="",
):
    if not op_icon or op_icon == 'NONE':
        op_icon = 'BLANK1'
    op_props = layout.operator(bl_idname, text=text, icon=op_icon)
    feed_op_props(op_props, op_kwargs)
    return op_props


def draw_drag_operator(
    rig: Object,
    parent_ui_data: OrderedDict,
    ui_data: OrderedDict,
    ui_name: str,
    ui_path: list[str],
    layout: UILayout,
):
    sub_elements = [elem for key, elem in parent_ui_data.items() if type(elem) != str]
    if len(sub_elements) > 1 and is_ui_edit_mode(rig):
        is_dragged = ui_data.get('is_dragged', False)
        icon = 'TRACKER'
        icon_value = 0
        if is_dragged:
            icon = 'VIEW_PAN'
            icon_value = 0
        elif cloudrig_addon:
            icon = 'NONE'
            icon_value = icons.get_cloudrig_icon_id('vertical_twoway_arrows')
        op = layout.operator(
            'pose.cloudrig_reorder_rows', text="", icon=icon, icon_value=icon_value
        )
        op.ui_path = json.dumps(ui_path + [ui_name])
        return op


def is_ui_edit_mode(obj):
    return (
        hasattr(obj, 'cloudrig') and obj.cloudrig.enabled and obj.cloudrig.ui_edit_mode
    )


def feed_op_props(op_props, op_kwargs: str or dict or list):
    """Set the arguments of an OperatorProperties instance, such as one returned by
    `UILayout.operator()`.
    """

    if type(op_kwargs) == str:
        op_kwargs = ast.literal_eval(op_kwargs)
    if type(op_kwargs) == dict:
        op_kwargs = [(key, value) for key, value in op_kwargs.items()]

    # Pass on any paramteres to the operator that it will accept.
    for key, value in op_kwargs:
        if hasattr(op_props, key):
            desired_type = type(getattr(op_props, key))
            # Lists and Dicts cannot be passed to blender operators, so we must convert them to a string.
            if type(value) in {list, dict}:
                value = json.dumps(value)
            if desired_type != type(value):
                value = desired_type(value)
            setattr(op_props, key, value)


def unquote_custom_prop_name(prop_name: str) -> str:
    if prop_name.startswith('["') or prop_name.startswith("['"):
        return prop_name[2:-2]
    return prop_name


class CloudRig_UIElement(PropertyGroup):
    @property
    def rig(self):
        return self.id_data

    element_type: EnumProperty(
        name="Element Type",
        description="How this UI element is drawn",
        items=[
            ('PANEL', "Panel", "Collapsible panel. May contain Panels, Labels, Rows"),
            ('LABEL', "Label", "Label. May contain Panels, Labels, Rows"),
            (
                'ROW',
                "Row",
                "Grouping for elements that allow multiple per row. Must be used for such elements, even if there is only one in the row. May contain Rows, Properties, and Operators",
            ),
            (
                'PROPERTY',
                "Property",
                "A single Property. Must belong to a Row. May contain conditional Panels, Labels, Rows",
            ),
            ('OPERATOR', "Operator", "A single Operator. Must belong to a Row"),
        ],
    )

    display_name: StringProperty(
        name="Display Name",
        description="Display name of this UI element",
        default="",
    )
    # NOTE: This needs to be updated when elements are removed.
    parent_index: IntProperty(
        # Supported Types: Panel, Label, Row.
        # TODO: Deletion will need to treat this carefully!
        name="Parent Index",
        description="Index of the parent UI element",
        default=-1,
    )

    @property
    def parent(self):
        if self.parent_index >= 0:
            return self.rig.cloudrig_ui[self.parent_index]

    @parent.setter
    def parent(self, value: 'CloudRig_UIElement'):
        if not value:
            self.parent_index = -1
        else:
            self.parent_index = value.index

    @property
    def index(self):
        for i, elem in enumerate(self.rig.cloudrig_ui):
            if elem == self:
                return i
        return -1

    @property
    def identifier(self):
        id = self.display_name
        parent = self.parent
        while parent:
            id = parent.display_name + " -> " + id
            parent = parent.parent
        return id

    parent_values: StringProperty(
        # Supported Types: Panel, Label, Row, only when Element Type of parent element is Property.
        name="Parent Values",
        description="Condition for this UI element to be drawn, when its parent is a Property. This UI element will only be drawn if the parent property has one of these comma-separated values",
    )

    texts: StringProperty(
        # Supported Types: Property, only Boolean and Integer.
        name="Texts",
        description="Comma-separated display texts for Integer and Boolean Properties",
    )

    bl_idname: StringProperty(
        # Supported Types: Operator
        name="Operator ID",
        description="Operator bl_idname",
    )
    op_kwargs: StringProperty(
        # Supported Types: Operator
        name="Operator Arguments",
        description="Operator Keyword Arguments, as a json dict",
        default="{}",
    )
    icon: StringProperty(
        # Supported Types: Label, Row, Property(bool), Operator
        name="Icon",
        description="Icon",
    )
    icon_false: StringProperty(
        # Supported Types: Property(bool)
        name="Icon False",
        description="Icon to display when this boolean property is False",
    )

    prop_owner_path: StringProperty(
        # Supported Types: Property
        name="Property Owner",
        description="Data Path from the rig object to the direct owner of the property to be drawn",
    )

    @property
    def prop_owner(self):
        try:
            return self.rig.path_resolve(self.prop_owner_path)
        except ValueError:
            # This can happen eg. if user adds a constraint influence to the UI, then deletes the constraint.
            return

    def update_prop_name(self, context):
        if self.is_custom_prop:
            self.display_name = self.prop_name.replace("_", " ").title()
        elif self.prop_name == 'is_visible':
            self.display_name = self.prop_owner.name

    prop_name: StringProperty(
        # Supported Types: Property
        name="Property Name",
        description="Name of the property to be drawn",
        update=update_prop_name,
    )

    @property
    def bracketed_prop_name(self):
        if self.is_custom_prop:
            return f'["{self.prop_name}"]'
        return self.prop_name

    @property
    def prop_value(self):
        if not hasattr(self.prop_owner, 'path_resolve'):
            print("cloudrig.py: Cannot resolve path from: ", self.prop_owner)
            return
        try:
            return self.prop_owner.path_resolve(self.bracketed_prop_name)
        except ValueError:
            # Property may have been removed.
            return {'MISSING'}

    is_custom_prop: BoolProperty(
        # Supported Types: Property # TODO: This should be set from the update of prop_name.
        name="Is Custom Property",
        description="Whether this is a custom or a built-in property. Set automatically",
    )

    @property
    def custom_prop_settings(self):
        if not self.is_custom_prop:
            return
        try:
            return self.prop_owner.id_properties_ui(self.prop_name).as_dict()
        except TypeError:
            # This happens for Python properties. There's no point drawing them.
            return

    @property
    def children(self):
        return [elem for elem in self.rig.cloudrig_ui if elem.parent == self]

    @property
    def should_draw(self):
        if not self.parent:
            return True
        if self.parent.element_type != 'PROPERTY':
            return True
        parent_value_str = str(self.parent.prop_value)
        if parent_value_str in [v.strip() for v in self.parent_values.split(",")]:
            return True
        return False

    def draw_ui_element(self, context, layout):
        if not self.should_draw or not layout:
            return

        parent_layout = remove_op_ui = layout

        if self.element_type == 'PANEL':
            # TODO: Figure out how to allow elements to be drawn in the header.
            header, layout = layout.panel(idname=str(self.index) + self.display_name)
            header.label(text=self.display_name)
            remove_op_ui = header
        if self.element_type == 'LABEL':
            layout = remove_op_ui = layout.row()
            if self.display_name:
                layout.label(text=self.display_name)
        if self.element_type == 'ROW':
            layout = remove_op_ui = parent_layout = layout.row()
            # if self.display_name:
            #     layout.label(text=self.display_name)
        if self.element_type == 'PROPERTY':
            if not self.parent or self.parent.element_type != 'ROW':
                layout = remove_op_ui = layout.row()
            self.draw_property(context, layout)
            if any([child.should_draw for child in self.children]):
                layout = layout.box()
        if self.element_type == 'OPERATOR':
            self.draw_operator(context, layout)

        if not layout:
            return
        for child in self.children:
            child.draw_ui_element(context, parent_layout)

        if self.rig.cloudrig.ui_edit_mode:
            remove_op_ui.operator(
                'object.cloudrig_ui_element_remove', text="", icon='X'
            ).element_index = self.index

    def draw_property(self, context, layout):
        prop_owner, prop_value = self.prop_owner, self.prop_value
        if not prop_owner:
            layout.alert = True
            layout.label(
                text=f"Missing property owner: '{self.prop_owner_path}' for property '{self.prop_name}'.",
                icon='ERROR',
            )
            return
        if prop_value == {'MISSING'}:
            layout.alert = True
            layout.label(
                text=f"Missing property '{self.prop_name}' of owner '{self.prop_owner_path}'.",
                icon='ERROR',
            )
            return

        display_name = self.display_name or self.prop_name

        bracketed_prop_name = self.bracketed_prop_name
        value_type, is_array = rna_idprop_value_item_type(prop_value)

        if value_type is type(None) or issubclass(value_type, ID):
            # Property is a Datablock Pointer.
            layout.prop(self.prop_owner, bracketed_prop_name, text=display_name)
        elif value_type in {int, float, bool}:
            if (
                self.texts
                and not is_array
                and len(self.texts) - 1 >= int(prop_value) >= 0
            ):
                text = self.texts[int(prop_value)].strip()
                if text:
                    display_name += ": " + text
            if value_type == bool:
                icon = self.icon if prop_value else self.icon_flase
                layout.prop(
                    self.prop_owner,
                    bracketed_prop_name,
                    toggle=True,
                    text=display_name,
                    icon=icon,
                )
            elif value_type in {int, float}:
                if self.is_custom_prop:
                    # Property is a float/int/color
                    # For large ranges, a slider doesn't make sense.
                    prop_settings = self.custom_prop_settings
                    is_slider = (
                        not is_array
                        and prop_settings['soft_max'] - prop_settings['soft_min'] < 100
                    )
                    layout.prop(
                        prop_owner,
                        bracketed_prop_name,
                        slider=is_slider,
                        text=display_name,
                    )
                else:
                    layout.prop(prop_owner, bracketed_prop_name, text=display_name)
        elif value_type == str:
            if (
                issubclass(type(prop_owner), bpy.types.Constraint)
                and bracketed_prop_name == 'subtarget'
                and prop_owner.target
                and prop_owner.target.type == 'ARMATURE'
            ):
                # Special case for nice constraint sub-target selectors.
                layout.prop_search(
                    prop_owner, bracketed_prop_name, prop_owner.target.pose, 'bones'
                )
            else:
                layout.prop(prop_owner, bracketed_prop_name)
        else:
            layout.prop(prop_owner, bracketed_prop_name, text=display_name)

    def draw_operator(self, context, layout):
        op_icon = self.icon
        if not self.icon or self.icon == 'NONE':
            op_icon = 'BLANK1'
        op_props = layout.operator(self.bl_idname, text=self.display_name, icon=op_icon)
        feed_op_props(op_props, self.op_kwargs)
        return op_props

    def reset(self):
        rna = self.bl_rna
        for prop_name, prop_data in rna.properties.items():
            if prop_name == 'rna_type':
                continue
            setattr(self, prop_name, prop_data.default)

    def __repr__(self):
        return self.identifier


class CLOUDRIG_PT_custom_ui(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_custom_ui"
    bl_label = "Rig UI"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout = layout.column(align=True)

        rig = context.active_object  # TODO

        for elem in rig.cloudrig_ui:
            if not elem.parent:
                elem.draw_ui_element(context, layout)


#######################################
########### Rig Preferences ###########
#######################################


class CloudRig_RigPreferences(PropertyGroup):
    collection_ui_type: EnumProperty(
        name="Collections UI Type",
        description="Whether to use Blender's built-in Collections UI or CloudRig's",
        items=[
            ('DEFAULT', 'Default', "Use Blender's built-in collections UI"),
            ('CLOUDRIG', 'CloudRig', "Use CloudRig's custom collections UI"),
        ],
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    show_visibility: BoolProperty(
        name="Hide",
        description="Show the Hide setting",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_solo: BoolProperty(
        name="Isolate",
        description="Show the Isolate operator",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_select: BoolProperty(
        name="Select",
        description="Show the Select operator",
        default=True,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_editing: BoolProperty(
        name="Editing",
        description="Show collection editing functions",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_bone_count: BoolProperty(
        name="Bone Count",
        description="Show number of bones selected/assigned (including child collections)",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )
    show_local_overrides: BoolProperty(
        name="Show Link",
        description="Show an icon indicating whether a collection is a local override. Locally created collections can be renamed, removed, sorted, and parented amongst each other, but the linked collection tree from the original file cannot be modified",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    def update_collection_filter(self, context=None):
        self.keep_active_collection_visible()

    collection_filter: bpy.props.StringProperty(
        name="Collection Filter",
        description="Search collections by name (case-sensitive)",
        update=update_collection_filter,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    def keep_active_collection_visible(self):
        colls = self.id_data.data.collections
        all_colls = self.id_data.data.collections_all
        if not colls:
            return

        flt_flags = CLOUDRIG_UL_collections.get_filter_flags(
            all_colls, self.collection_filter
        )

        new_idx = self.active_collection_index

        if new_idx == -1:
            # Means no collection is active, which is allowed, when there is
            # a name search filter entered, resulting in 0 matches.
            colls.active_index = -1
            return
        if new_idx < 0:
            new_idx = -1
        if new_idx > len(all_colls) - 1:
            new_idx = len(all_colls) - 1

        if flt_flags[new_idx] == 0:
            # If the new active element would be hidden, keep going up the list until a visible one is found.
            while flt_flags[new_idx] == 0 and new_idx > 0:
                new_idx -= 1
        if flt_flags[new_idx] == 0:
            # If that failed, go down the list instead.
            new_idx = self.active_collection_index + 1
            while flt_flags[new_idx] == 0 and new_idx < len(all_colls):
                new_idx += 1
        if flt_flags[new_idx] == 0:
            # If that fails too, don't allow an active element.
            new_idx = -1

        if new_idx != self.active_collection_index:
            # This will cause this function to get called again, but this time,
            # none of the if-statements should trigger.
            self.active_collection_index = new_idx
            return

        colls.active_index = self.active_collection_index

    def sync_collection_names(self):
        for coll in self.id_data.data.collections_all:
            coll.cloudrig_info.name = coll.name

    def update_active_collection_index(self, context=None):
        self.sync_collection_names()
        self.keep_active_collection_visible()

    active_collection_index: IntProperty(
        name="Bone Collections",
        description="Bone Collections",
        update=update_active_collection_index,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )


#######################################
###### Nested Bone Collections ########
#######################################


class CloudRigBoneCollection(PropertyGroup):
    """Properties stored on BoneCollection.cloudrig_info.
    Used for implementing and drawing the nested collections UIList.
    Also some other functionality like Solo Collection and Preserve on Regenerate.
    """

    def get_collection(self) -> BoneCollection:
        """Return the BoneCollection that this instance of this class belongs to."""
        armature = self.id_data
        for coll in armature.collections_all:
            if coll.cloudrig_info == self:
                return coll

    def update_name(self, context):
        """Runs when trying to change the name of this instance, which should stay in sync
        with the collection it's masking."""

        coll = self.get_collection()

        # If the name didn't change, don't do anything.
        if coll.name == self.name:
            return

        # If the collection is not editable, don't allow changing the name.
        if not coll.is_editable:
            self.name = coll.name
            return

        # Force the name to be unique.
        if self.name in self.id_data.collections_all:
            counter = 1
            base_name = self.name
            unique_name = base_name
            while unique_name in self.id_data.collections_all:
                unique_name = base_name + "." + str(counter).zfill(3)
                counter += 1
            # This will cause update_name() to be called again,
            # but this time this `if` block won't trigger.
            self.name = unique_name
            return

        def cleanup_garbage_bone_sets(component):
            # Clean up old bone set data.
            for bone_set_name in list(component.params.bone_sets.keys()):
                if not hasattr(component.params.bone_sets, bone_set_name):
                    del component.params.bone_sets[bone_set_name]
            for bone_set_name in list(component.ui_bone_sets.keys()):
                if not hasattr(component.params.bone_sets, bone_set_name):
                    entry_idx = component.ui_bone_sets.find(bone_set_name)
                    component.ui_bone_sets.remove(entry_idx)
            if not component.active_bone_set:
                component.bone_sets_active_index = 0

        # Metarig: Update bone sets with this collection assigned to refer to the new name.
        if is_active_cloud_metarig(context):
            rig = context.pose_object or context.active_object
            for pb in rig.pose.bones:
                comp = pb.cloudrig_component
                if not comp or not comp.component_type:
                    continue
                cleanup_garbage_bone_sets(comp)
                for bone_set_name in list(comp.params.bone_sets.keys()):
                    bone_set = getattr(comp.params.bone_sets, bone_set_name)
                    for bone_set_coll in bone_set.collections:
                        if bone_set_coll.name == coll.name:
                            bone_set_coll.name = self.name
                            break

        # Set the actual collection's name to be in sync.
        coll.name = self.name

    name: StringProperty(
        name="Name",
        description="Name of this bone collection",
        update=update_name,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    is_dragged: BoolProperty(
        name="Is Dragged",
        description="Internal. Flag to mark that this collection is currently dragged by the reorder operator. Used to change the icon",
        default=False,
    )

    @property
    def are_parents_visible(self):
        parent = self.parent_collection
        if not parent:
            return True

        while parent:
            if not parent.is_visible:
                return False
            parent = parent.cloudrig_info.parent_collection

        return True

    @property
    def parent_collection(self) -> BoneCollection:
        return self.get_collection().parent

    @parent_collection.setter
    def parent_collection(self, coll: BoneCollection):
        self.get_collection().parent = coll

    def unfold_parents(self):
        for parent in self.parents_recursive:
            parent.is_expanded = True

    def update_is_expanded(self, context):
        coll = self.get_collection()
        coll.is_expanded = self.is_expanded
        rig = find_cloudrig(context)
        if rig:
            rig.cloudrig_prefs.active_collection_index = coll.index

    is_expanded: BoolProperty(
        name="Is Expanded",
        description="Whether to show the children of this collection",
        default=False,
        update=update_is_expanded,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def siblings(self):
        """Includes self!"""
        if not self.parent_collection:
            all_colls = self.id_data.collections_all
            return [
                coll for coll in all_colls if not coll.cloudrig_info.parent_collection
            ]
        return self.parent_collection.children

    @property
    def children_recursive(self) -> list[BoneCollection]:
        all_children = self.get_collection().children[:]
        for child in all_children:
            all_children += child.children
        return all_children

    @property
    def parents_recursive(self) -> list[BoneCollection]:
        parents = []
        parent = self.parent_collection
        while parent:
            parents.append(parent)
            parent = parent.cloudrig_info.parent_collection
        return parents

    quick_access: BoolProperty(
        name="Quick Access",
        description="Toggle whether this collection should appear in the quick access list",
        default=False,
        options={'LIBRARY_EDITABLE'},
        override={'LIBRARY_OVERRIDABLE'},
    )

    @property
    def are_parents_unfolded(self):
        """Return False if any parent up the chain has is_expanded=False"""
        if not self.parent_collection:
            return True

        return all([parent.is_expanded for parent in self.parents_recursive])

    @property
    def hierarchy_depth(self):
        """Return number of parents"""
        return len(self.parents_recursive)

    preserve_on_regenerate: BoolProperty(
        name="Preserve On Regenerate",
        description="Should be enabled on manually defined collections, to preserve them and their assigned bones on re-generating from the metarig",
        default=False,
    )


class CLOUDRIG_UL_collections(UIList):
    """Draw bone collections with nesting support"""

    @staticmethod
    def draw_collection(context, layout, collection, idx):
        cloudrig_info = collection.cloudrig_info
        rig = context.pose_object or context.active_object
        prefs = rig.cloudrig_prefs

        row = layout.row(align=True)
        if collection.parent:
            split = row.split(factor=0.02 * cloudrig_info.hierarchy_depth)
            split.row()
            row = split.row(align=True)
            row = row.row(align=True)
        if collection.children:
            icon = 'DOWNARROW_HLT' if collection.is_expanded else 'RIGHTARROW'
            row.prop(
                collection.cloudrig_info,
                'is_expanded',
                text="",
                icon=icon,
                emboss=False,
            )
        else:
            row.label(text="", icon='BLANK1')

        if prefs.show_local_overrides and collection.is_local_override:
            row.prop(
                cloudrig_info,
                'name',
                text="",
                icon='LIBRARY_DATA_OVERRIDE',
                emboss=False,
            )
        else:
            row.prop(cloudrig_info, 'name', text="", emboss=False)

        if context.mode != 'EDIT_ARMATURE':
            direct_selected_bones = [
                b
                for b in collection.bones
                if not b.hide
                and any([c.is_visible for c in b.collections])
                and b.select
            ]
            indirect_bones = collection.bones_recursive
            indirect_visible_bones = [
                b
                for b in indirect_bones
                if not b.hide and any([c.is_visible for c in b.collections])
            ]
            indirect_selected_bones = [b for b in indirect_visible_bones if b.select]

            if direct_selected_bones:
                row.label(text="", icon='LAYER_ACTIVE')
            elif indirect_selected_bones:
                row.label(text="", icon='LAYER_USED')

            if prefs.show_bone_count:
                row.label(
                    text=f"{len(indirect_selected_bones)}/{len(indirect_bones)}",
                    icon='BONE_DATA',
                )

        vis_row = row.row(align=True)
        vis_row.operator_context = 'INVOKE_DEFAULT'
        vis_row.enabled = cloudrig_info.are_parents_visible
        if prefs.show_visibility:
            icon = 'HIDE_OFF' if collection.is_visible else 'HIDE_ON'
            vis_row.prop(collection, 'is_visible', text="", icon=icon)
        if prefs.show_select:
            sel_op = vis_row.operator(
                POSE_OT_cloudrig_collection_select.bl_idname,
                text="",
                icon='MOUSE_LMB',
            )
            sel_op.collection_name = collection.name
            sel_op.reveal_bones = False
        row = row.row(align=True)
        if prefs.show_solo:
            icon = 'SOLO_ON' if collection.is_solo else 'SOLO_OFF'
            row.prop(collection, 'is_solo', text="", icon=icon)
        if prefs.show_editing:
            row.separator()

            icon = 'RECORD_ON' if cloudrig_info.quick_access else 'RECORD_OFF'
            row.prop(cloudrig_info, 'quick_access', text="", icon=icon)
            if is_active_cloudrig(context) and find_metarig_of_rig(
                context, context.active_object
            ):
                icon = (
                    'FAKE_USER_ON'
                    if cloudrig_info.preserve_on_regenerate
                    else 'FAKE_USER_OFF'
                )
                row.prop(cloudrig_info, 'preserve_on_regenerate', text="", icon=icon)

            if collection.is_editable:
                icon = 'TRACKER'
                if collection.cloudrig_info.is_dragged:
                    icon = 'VIEW_PAN'
                row.operator(
                    POSE_OT_cloudrig_reorder_collections.bl_idname, text="", icon=icon
                ).collection_name = collection.name

        return row

    def draw_item(
        self,
        context,
        layout,
        armature,
        item,
        _icon_value,
        _active_data,
        _active_propname,
    ):
        idx = armature.collections_all.find(item.name)
        self.draw_collection(context, layout, item, idx)

    def draw_filter(self, context, layout):
        """Don't draw sorting buttons here, since the displayed order should ALWAYS
        show the order in which the rig components will be executed during generation.
        """
        rig = context.pose_object or context.active_object
        layout.prop(rig.cloudrig_prefs, "collection_filter", text="")

    @staticmethod
    def get_visual_collection_order(rig, filtered=False) -> list[BoneCollection]:
        """Return the collections of the rig in the order they are currently to be displayed in the UIList.
        If filtered, only include those collections in the list which aren't being filtered, eg. by collapsing parents, or search.
        """

        # Find collections without any parent
        all_collections = rig.data.collections_all
        root_colls = [coll for coll in all_collections if not coll.parent]
        sorted_colls = []

        def add_children_recursive(parent_coll):
            sorted_colls.append(parent_coll)
            for child in parent_coll.children:
                add_children_recursive(child)

        for root_coll in root_colls:
            add_children_recursive(root_coll)

        flt_flags = CLOUDRIG_UL_collections.get_filter_flags(
            all_collections, rig.cloudrig_prefs.collection_filter
        )

        if filtered:
            for i, flag in enumerate(flt_flags):
                if flag == 0:
                    sorted_colls.remove(all_collections[i])

        return sorted_colls

    @staticmethod
    def get_collection_order(rig) -> list[int]:
        # Order collections by CloudRig hierarchy, such that children come after their
        # parents, but the original order is otherwise preserved.

        sorted_colls = CLOUDRIG_UL_collections.get_visual_collection_order(rig)
        # NOTE: THIS MUST BE BOMBPROOF, OR BLENDER WILL CRASH!
        return [sorted_colls.index(coll) for coll in rig.data.collections_all]

    @staticmethod
    def get_filter_flags(all_collections, filter_name):
        flt_flags = [1 << 30] * len(all_collections)
        # Filtering by name search.
        if filter_name:
            helper_funcs = bpy.types.UI_UL_list
            flt_flags = helper_funcs.filter_items_by_name(
                filter_name,
                1 << 30,
                all_collections,
                "name",
                reverse=False,
            )

        # Filter out collections whose parents are collapsed
        return [
            flag * int(all_collections[i].cloudrig_info.are_parents_unfolded)
            for i, flag in enumerate(flt_flags)
        ]

    def filter_items(self, context, data, propname):
        all_collections = getattr(data, propname)
        rig = find_cloudrig(context)

        flt_flags = self.get_filter_flags(
            all_collections, rig.cloudrig_prefs.collection_filter
        )
        flt_neworder = self.get_collection_order(rig)

        return flt_flags, flt_neworder


def draw_cloudrig_collections(self, context, rig: Object):
    layout = self.layout
    layout.use_property_split = True
    layout.use_property_decorate = False

    prop_owner = 'pose_object'
    if context.active_object:
        prop_owner = 'active_object'
        if context.active_object != rig:
            _rig, modifier_name = get_cloudrig_of_mesh(context.active_object)
            if modifier_name:
                prop_owner = f'active_object.modifiers["{modifier_name}"].object'

    list_col = draw_ui_list(
        layout,
        context,
        class_name='CLOUDRIG_UL_collections',
        list_path=prop_owner + ".data.collections_all",
        active_index_path=prop_owner + '.cloudrig_prefs.active_collection_index',
        insertion_operators=False,
        move_operators=False,
        unique_id='CloudRig Nested Collections UI',
    )
    list_col.popover(
        panel="CLOUDRIG_PT_collections_filter",
        text="",
        icon='FILTER',
    )

    list_col.separator()

    prefs = rig.cloudrig_prefs
    if not prefs.show_editing:
        list_col.operator(
            POSE_OT_cloudrig_collections_reveal_all.bl_idname,
            text="",
            icon='HIDE_OFF',
            emboss=False,
        )
        list_col.operator(
            'armature.collection_unsolo_all',
            text="",
            icon='SOLO_OFF',
            emboss=False,
        )
        return

    list_col.operator(POSE_OT_cloudrig_collection_add.bl_idname, text="", icon='ADD')

    list_col.operator(
        POSE_OT_cloudrig_collection_delete.bl_idname, text="", icon='REMOVE'
    ).mode = 'ACTIVE'
    list_col.separator()

    row = list_col.row()
    row.menu(CLOUDRIG_MT_collections_specials.bl_idname, text="", icon='DOWNARROW_HLT')

    list_col.separator()

    active_coll = rig.data.collections.active
    if not active_coll:
        return

    row = layout.row()
    sub = row.row(align=True)
    sub.operator(POSE_OT_cloudrig_collection_assign.bl_idname, text="Assign").assign = (
        True
    )
    sub.operator(
        POSE_OT_cloudrig_collection_assign.bl_idname, text="Unassign"
    ).assign = False

    sub = row.row(align=True)
    sel_op = sub.operator(POSE_OT_cloudrig_collection_select.bl_idname, text="Select")
    sel_op.select = True
    sel_op.collection_name = active_coll.name

    desel_op = sub.operator(
        POSE_OT_cloudrig_collection_select.bl_idname, text="Deselect"
    )
    desel_op.select = False
    desel_op.collection_name = active_coll.name


class CLOUDRIG_PT_collections_sidebar(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_collections_sidebar"
    bl_label = "Bone Collections"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context)

    def draw(self, context):
        rig = find_cloudrig(context)
        draw_cloudrig_collections(self, context, rig)


class CLOUDRIG_PT_collections_filter(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_label = "Filter"
    bl_options = {'INSTANCED'}

    def draw(self, context):
        layout = self.layout
        rig = find_cloudrig(context)
        prefs = rig.cloudrig_prefs
        row = layout.row(align=True)
        row.prop(prefs, 'show_visibility', text="", icon='HIDE_OFF')
        row.prop(prefs, 'show_solo', text="", icon='SOLO_OFF')
        row.prop(prefs, 'show_select', text="", icon='RESTRICT_SELECT_OFF')

        row.separator()
        row.prop(prefs, "show_editing", text="", icon='PREFERENCES')
        row.prop(prefs, 'show_bone_count', text="", icon='GROUP_BONE')
        if rig.data.override_library:
            row.prop(
                prefs, 'show_local_overrides', text="", icon='LIBRARY_DATA_OVERRIDE'
            )


class CLOUDRIG_MT_collections_specials(Menu):
    bl_label = "Collection Operators"
    bl_idname = 'CLOUDRIG_MT_collections_specials'

    def draw(self, context):
        layout = self.layout
        layout.operator(
            POSE_OT_cloudrig_collections_reveal_all.bl_idname,
            text="Show All",
            icon='HIDE_OFF',
        )
        layout.operator(
            'armature.collection_unsolo_all',
            text="Unsolo All",
            icon='SOLO_OFF',
        )
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_collection_assign.bl_idname,
            text="Unassign Selected Bones from All Collections",
            icon='REMOVE',
        )
        layout.operator(
            POSE_OT_cloudrig_collection_delete.bl_idname,
            text="Delete Hierarchy of Collections",
            icon='OUTLINER',
        ).mode = 'HIERARCHY'
        layout.operator(
            POSE_OT_cloudrig_collection_delete.bl_idname,
            text="Delete All Local Collections",
            icon='TRASH',
        ).mode = 'ALL'
        layout.separator()
        layout.operator(
            POSE_OT_cloudrig_collection_clipboard_copy.bl_idname,
            text="Copy Visible Collections to Clipboard",
            icon='COPYDOWN',
        )
        layout.operator(
            POSE_OT_cloudrig_collection_clipboard_paste.bl_idname,
            text="Paste Collections from Clipboard",
            icon='PASTEDOWN',
        )


class CLOUDRIG_MT_collections_quick_select(Menu):
    """Quick select menu, so favourite bone collections can be selected quickly with a hotkey"""

    bl_label = "Quick Select"
    bl_idname = 'CLOUDRIG_MT_collections_quick_select'

    @classmethod
    def poll(cls, context):
        return find_cloudrig(context, allow_metarigs=False)

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"

        rig = find_cloudrig(context, allow_metarigs=False)

        def collections_recursive(colls):
            """This has a different order from collections_all, which aligns with
            user expectation (UI top to bottom order)."""
            for coll in colls:
                yield coll
                if coll.children:
                    yield from collections_recursive(coll.children)

        for coll in collections_recursive(rig.data.collections):
            if coll.cloudrig_info.quick_access:
                op = layout.operator(
                    POSE_OT_cloudrig_collection_select.bl_idname,
                    text=coll.name,
                    icon='RESTRICT_SELECT_OFF',
                )
                op.collection_name = coll.name
                op.select = True
                op.reveal_bones = False


class POSE_OT_cloudrig_collections_reveal_all(CloudRigOperator):
    """Reveal all collections"""

    bl_idname = "pose.cloudrig_collections_reveal_all"
    bl_label = "Show All Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = find_cloudrig(context)
        for coll in rig.data.collections_all:
            coll.is_visible = True
            coll.is_solo = False

        return {'FINISHED'}


@contextlib.contextmanager
def pose_mode(rig):
    if rig.mode == 'POSE':
        yield

    else:
        mode_bkp = rig.mode
        bpy.ops.object.mode_set(mode='POSE')
        yield
        bpy.ops.object.mode_set(mode=mode_bkp)


class POSE_OT_cloudrig_collection_select(CloudRigOperator):
    "Select all bones in this collection.\n\n" "Shift: Extend selection.\n" "Ctrl: Mirror selection.\n" "Alt: Deselect"

    bl_idname = "pose.cloudrig_collection_select"
    bl_label = "Select Bones of Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    collection_name: StringProperty(
        name="Name",
        description="Name of the collection to operate on",
        options={'SKIP_SAVE'},
    )
    extend_selection: BoolProperty(
        name="Expand Selection",
        description="Whether the existing selection should be preserved",
        default=False,
        options={'SKIP_SAVE'},
    )
    select: BoolProperty(
        name="Selection State",
        description="Whether the collection's bones should be selected or deselected",
        default=True,
        options={'SKIP_SAVE'},
    )
    reveal_bones: BoolProperty(
        name="Reveal Bones",
        description="Whether bones of the collection should be un-hidden",
        default=False,
        options={'SKIP_SAVE'},
    )
    flip: BoolProperty(
        name="Flip",
        description="Whether to operate on the opposite side of this collection's bones",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, props):
        if not props.select:
            return "Deselect the bones of this collection"

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(
            cls, context, modes={'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}
        )

    def invoke(self, context, event):
        self.extend_selection = event.shift
        self.select = not event.alt
        self.flip = event.ctrl

        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)

        collection = rig.data.collections_all.get(self.collection_name)

        if not collection:
            collection = rig.data.collections.active
        if not collection:
            return {'CANCELLED'}

        reveal_colls = [collection]
        if self.select and self.reveal_bones:
            reveal_colls += collection.cloudrig_info.children_recursive

        for reveal_coll in reveal_colls:
            reveal_coll.is_visible = True

        with pose_mode(rig):
            if not self.extend_selection and self.select:
                for bone in rig.data.bones:
                    bone.select = False

            for bone in collection.bones_recursive:
                if self.flip:
                    bone = rig.data.bones.get(bpy.utils.flip_name(bone.name))
                    if not bone:
                        continue
                if self.reveal_bones and self.select:
                    bone.hide = False
                bone.select = self.select

        return {'FINISHED'}


def poll_cloudrig_operator_collection(operator, context):
    rig = poll_cloudrig_operator(operator, context)
    if not rig:
        return False
    active_coll = rig.data.collections.active
    if not active_coll:
        operator.poll_message_set("No active operator.")
        return False
    if not active_coll.is_editable:
        operator.poll_message_set("Cannot delete linked collection.")
        return False
    return True


class POSE_OT_cloudrig_collection_delete(CloudRigOperator):
    "Remove the active bone collection.\n" "Shift: Delete whole hierarchy" ""

    bl_idname = "pose.cloudrig_collection_delete"
    bl_label = "Remove Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    mode: EnumProperty(
        items=[
            ('ACTIVE', "Active", "Delete the Active collection"),
            ('HIERARCHY', "Hierarchy", "Delete the Active collection and its children"),
            ('ALL', "All", "Delete all local collections"),
        ]
    )

    @classmethod
    def poll(cls, context):
        rig = poll_cloudrig_operator_collection(cls, context)
        if not rig:
            return False
        return True

    def invoke(self, context, event):
        if self.mode == 'ACTIVE' and event.shift:
            self.mode = 'HIERARCHY'
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        visual_index = self.get_visual_active_index(rig)

        if self.mode == 'ALL':
            self.delete_all(rig)
            self.report({'INFO'}, "Deleted all editable bone collections.")
            return {'FINISHED'}

        if self.mode == 'ACTIVE' and not self.delete_active(rig):
            return {'CANCELLED'}

        elif self.mode == 'HIERARCHY':
            self.delete_hierarchy(rig)
            self.report(
                {'INFO'}, "Deleted editable bone collections of selected hierarchy."
            )

        self.set_visual_active_index(rig, visual_index)

        return {'FINISHED'}

    @staticmethod
    def get_visual_active_index(rig) -> int:
        """Get the index of the active collection as it is in the current UIList.
        Eg., if the active collection is the 3rd one that is drawn, this will return 2.
        """
        sorted_collections = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        return sorted_collections.index(rig.data.collections.active)

    def set_visual_active_index(self, rig, index):
        """Set the index of the active collection as they appear in the UIList.
        Eg., if index==2, the 3rd collection from the top of the list will become active.
        """
        sorted_collections = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        if index <= len(sorted_collections) - 1:
            coll = sorted_collections[index]
        elif len(sorted_collections) > 0:
            coll = sorted_collections[index - 1]
        else:
            return
        rig.cloudrig_prefs.active_collection_index = coll.index

    def delete_active(self, rig) -> bool:
        """Try to delete the active bone collection, and return success state."""
        coll = rig.data.collections.active
        if not coll:
            self.report({'ERROR'}, "There is no active collection.")
            return False
        if not coll.is_editable:
            self.report({'ERROR'}, "Cannot delete linked collection.")
            return False

        coll_name = coll.name
        rig.data.collections.remove(coll)
        self.report({'INFO'}, f"Deleted active collection: '{coll_name}'")
        return True

    def delete_hierarchy(self, rig):
        colls = rig.data.collections
        active = colls.active

        for child in active.cloudrig_info.children_recursive:
            if child.is_editable:
                colls.remove(child)
        colls.remove(active)

    def delete_all(self, rig):
        for coll in rig.data.collections_all[:]:
            if coll.is_editable:
                rig.data.collections.remove(coll)

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_add(CloudRigOperator):
    """Add a new bone collection"""

    bl_idname = "pose.cloudrig_collection_add"
    bl_label = "Add Bone Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def execute(self, context):
        rig = find_cloudrig(context)
        if rig.data.override_library:
            rig.data.override_library.is_system_override = False
        colls = rig.data.collections
        all_colls = rig.data.collections_all
        active_coll = colls.active
        active_idx = colls.active_index

        parent_coll = None
        if active_coll:
            parent_coll = active_coll.parent

        coll = colls.new(name="Collection")
        coll.parent = active_coll.parent
        coll.parent = parent_coll
        coll_idx = all_colls.find(coll.name)
        colls.move(coll_idx, active_idx + 1)

        coll.cloudrig_info.unfold_parents()
        rig.cloudrig_prefs.active_collection_index = all_colls.find(coll.name)

        return {'FINISHED'}


class POSE_OT_cloudrig_reorder_collections(CloudRigOperator):
    "Rearrange and re-parent this collection with the arrow keys, WASD, or by " "moving the mouse.\n\n" "Left-click/Enter: Confirm.\n" "Right-click/Esc: Cancel.\n" "Up/Down: Move Collection up/down.\n" "Left/Right: Parent/Unparent collection to the one above"

    bl_idname = "pose.cloudrig_reorder_collections"
    bl_label = "Reorder Collections"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    collection_name: StringProperty()

    def invoke(self, context, event):
        self.mouse_anchor_y = event.mouse_y
        self.mouse_anchor_x = event.mouse_x
        self.index_offset = 0

        rig = find_cloudrig(context)
        self.collection = rig.data.collections_all.get(self.collection_name)
        if not self.collection:
            return {'CANCELLED'}
        self.initial_parent = self.collection.parent
        self.collection.cloudrig_info.is_dragged = True
        rig.cloudrig_prefs.active_collection_index = self.initial_index = (
            self.collection.index
        )

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rig = find_cloudrig(context)
        self.index_offset = 0
        if (
            event.type in {'W', 'UP_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = -1
        elif (
            event.type in {'S', 'DOWN_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.index_offset = 1
        elif event.type == 'MOUSEMOVE':
            self.index_offset = int((event.mouse_y - self.mouse_anchor_y) / -20)
            if int((event.mouse_x - self.mouse_anchor_x) / 20) > 0:
                self.parent_active_coll_to_prev_sibling(rig)
                self.mouse_anchor_x = event.mouse_x
            elif int((event.mouse_x - self.mouse_anchor_x) / -20) > 0:
                self.unparent_active_coll_by_one(rig)
                self.mouse_anchor_x = event.mouse_x
        elif event.type in {'LEFTMOUSE', 'NUMPAD_ENTER', 'RET'}:
            self.collection.cloudrig_info.is_dragged = False
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.collection.cloudrig_info.is_dragged = False
            self.collection.parent = self.initial_parent
            rig.data.collections.move(self.collection.index, self.initial_index)
            rig.cloudrig_prefs.active_collection_index = self.collection.index
            return {'CANCELLED'}
        elif (
            event.type in {'RIGHT_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.parent_active_coll_to_prev_sibling(rig)
        elif (
            event.type in {'LEFT_ARROW'}
            and not event.is_repeat
            and event.value != 'RELEASE'
        ):
            self.unparent_active_coll_by_one(rig)

        if self.index_offset != 0:
            ret = self.move_active_coll_up_down(rig, self.index_offset)
            if ret == {'FINISHED'}:
                self.mouse_anchor_y = event.mouse_y

        return {'RUNNING_MODAL'}

    def unparent_active_coll_by_one(self, rig):
        active_coll = rig.data.collections.active
        if not active_coll.parent:
            return {'CANCELLED'}
        old_parent = active_coll.parent

        old_parent.is_expanded = False
        active_coll.parent = old_parent.parent
        rig.data.collections.move(active_coll.index, old_parent.index + 1)
        rig.cloudrig_prefs.active_collection_index = active_coll.index

        if active_coll.parent:
            self.report({'INFO'}, f"Parented to '{active_coll.parent.name}'.")
        else:
            self.report({'INFO'}, f"Set parent to None.")
        return {'FINISHED'}

    def parent_active_coll_to_prev_sibling(self, rig):
        active_coll = rig.data.collections.active
        prev_sibling = self.get_sibling_of_active_coll(
            rig, index_offset=-1, only_editable=True
        )
        if not prev_sibling:
            return {'CANCELLED'}

        prev_sibling.is_expanded = True
        active_coll.parent = prev_sibling

        rig.cloudrig_prefs.active_collection_index = active_coll.index

        if active_coll.parent:
            self.report({'INFO'}, f"Parented to '{active_coll.parent.name}'.")
        else:
            self.report({'INFO'}, f"Set parent to None.")
        return {'FINISHED'}

    def get_sibling_of_active_coll(
        self, rig, *, index_offset=-1, only_editable=False
    ) -> BoneCollection | None:
        visual_order = CLOUDRIG_UL_collections.get_visual_collection_order(
            rig, filtered=True
        )
        visual_index = POSE_OT_cloudrig_collection_delete.get_visual_active_index(rig)

        while True:
            visual_index += index_offset
            if visual_index < 0 or visual_index > len(visual_order) - 1:
                return None

            other_coll = visual_order[visual_index]
            if only_editable and not other_coll.is_editable:
                continue
            if other_coll.parent == self.collection.parent:
                return other_coll

    def move_active_coll_up_down(self, rig, index_offset=-1):
        active_coll = rig.data.collections.active
        sibling_coll = self.get_sibling_of_active_coll(rig, index_offset=index_offset)
        if not sibling_coll:
            return {'CANCELLED'}

        rig.data.collections.move(active_coll.index, sibling_coll.index)
        rig.cloudrig_prefs.active_collection_index = active_coll.index
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_assign(CloudRigOperator):
    "Assign selected bones to active collection.\n\n" "Alt: Un-assign.\n" "Shift: To active collection & children.\n" "Shift+Ctrl: To all collections"

    bl_idname = "pose.cloudrig_collection_assign"
    bl_label = "(Un)Assign Bones to Collection"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    assign: BoolProperty(default=True)
    all_collections: BoolProperty(default=False)
    assign_to_children: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        rig = poll_cloudrig_operator(
            cls, context, modes={'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}
        )
        if not rig:
            return False
        if not rig.data.collections.active:
            cls.poll_message_set("No active collection.")
            return False
        return True

    @classmethod
    def description(cls, context, props):
        if not props.assign:
            words = ("Assign", "to") if props.assign else ("Unassign", "from")
            colls = "all collections" if props.all_collections else "active collection"
            return f"{words[0]} selected bones {words[1]} {colls}"

    def invoke(self, context, event):
        if self.assign:
            self.assign = not event.alt
        self.assign_to_children = event.shift
        self.all_collections = event.shift and event.ctrl
        return self.execute(context)

    def execute(self, context):
        rig = find_cloudrig(context)
        colls = [rig.data.collections.active]
        if self.assign_to_children:
            colls += rig.data.collections.active.cloudrig_info.children_recursive

        if self.all_collections:
            colls = rig.data.collections_all

        with pose_mode(rig):
            if context.selected_bones:
                pbs = [rig.pose.bones.get(eb.name) for eb in context.selected_bones]
            else:
                pbs = context.selected_pose_bones
            for coll in colls:
                for pb in pbs:
                    if self.assign:
                        coll.assign(pb.bone)
                    else:
                        coll.unassign(pb.bone)

        # Report pretty info; Assigned/Unassigned, to/from, number of bones and collections,
        # or use the name if just 1.
        words = ("Assigned", "to") if self.assign else ("Unassigned", "from")
        bones = f"{len(pbs)} bones" if len(pbs) > 0 else pbs[0].name
        colls = f"{len(colls)} collections" if len(colls) > 0 else colls[0].name
        self.report({'INFO'}, f"{words[0]} {bones} {words[1]} {colls}.")

        return {'FINISHED'}


class POSE_OT_cloudrig_collection_clipboard_copy(CloudRigOperator):
    """Copy visible collections to Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_copy"
    bl_label = "Copy Visible Collections To Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def execute(self, context):
        rig = find_cloudrig(context)

        json_obj = defaultdict(dict)
        counter = 0
        for coll in rig.data.collections_all:
            if coll.is_visible:
                counter += 1
                json_obj[coll.name]['bone_names'] = [bone.name for bone in coll.bones]
                json_obj[coll.name]['cloudrig_info'] = coll['cloudrig_info'].to_dict()
                json_obj[coll.name]['parent_name'] = (
                    coll.parent.name if coll.parent else ""
                )

        if counter == 0:
            self.report({'ERROR'}, "No visible collections to copy.")
            return {'CANCELLED'}

        context.window_manager.clipboard = json.dumps(json_obj)

        self.report({'INFO'}, f"Copied {counter} collections to Blender clipboard.")
        return {'FINISHED'}


class POSE_OT_cloudrig_collection_clipboard_paste(CloudRigOperator):
    """Paste collections from the Blender clipboard"""

    bl_idname = "pose.cloudrig_collection_clipboard_paste"
    bl_label = "Paste Collections From Clipboard"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    overwrite_existing: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return poll_cloudrig_operator(cls, context)

    def execute(self, context):
        counter = 0
        try:
            json_obj = json.loads(context.window_manager.clipboard)
            rig = find_cloudrig(context)
            collections = rig.data.collections
            collections_all = rig.data.collections_all

            for coll_name, coll_data in json_obj.items():
                coll = collections_all.get(coll_name)

                if not coll or not self.overwrite_existing:
                    coll = collections.new(coll_name)
                    coll.cloudrig_info.name = coll.name

                if type(coll_data) == list:
                    # Selection Set.
                    bone_names = coll_data
                    coll.cloudrig_info.quick_access = True
                    coll.cloudrig_info.preserve_on_regenerate = True
                elif type(coll_data) == dict:
                    # CloudRig Collection.
                    cloudrig_info = coll_data['cloudrig_info']
                    bone_names = coll_data['bone_names']

                    for key, value in cloudrig_info.items():
                        setattr(coll.cloudrig_info, key, value)

                for bone_name in bone_names:
                    pb = rig.pose.bones.get(bone_name)
                    if not pb:
                        continue
                    coll.assign(pb)
                counter += 1

            # Iterate over everything again to assign the parents,
            # because collections_all is not in hierarchy order.
            for coll_name, coll_data in json_obj.items():
                coll = collections_all.get(coll_name)
                if 'parent_name' not in coll_data:
                    continue
                parent = collections_all.get(coll_data['parent_name'])
                coll.parent = parent

        except Exception as e:
            self.report(
                {'ERROR'},
                'The clipboard does not contain Bone Collections or Selection Sets.',
            )
            raise e

        if counter == 0:
            self.report({'ERROR'}, "No collections in clipboard to be pasted.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Pasted {counter} collections from clipboard.")
        return {'FINISHED'}


class ARMATURE_OT_bone_collections_popup(Operator):
    """Bone Collections pop-up"""

    bl_idname = "armature.bone_collections_popup"
    bl_label = "Bone Collections"
    # Undo step is omitted, since this is just a UI pop-up.
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)

    @classmethod
    def poll(cls, context):
        rig = context.pose_object or context.active_object
        return rig and rig.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout

        if context.pose_object:
            rig = context.pose_object
        else:
            rig = context.active_object

        layout.row().template_list(
            'CLOUDRIG_UL_collections',
            'Bone Collections Popover List',
            rig.data,
            'collections_all',
            rig.cloudrig_prefs,
            'active_collection_index',
            rows=10 if rig.data.collections_all else 1,
        )

    def execute(self, context):
        return {'FINISHED'}


def builtin_collections_draw_override(self, context):
    """Override the Bone Collections ui in the Properties Editor.
    Editor drawing code should use context.object, since this accounts for pinning.
    """
    pinned_obj = context.object
    if is_cloud_metarig(pinned_obj) or is_generated_cloudrig(pinned_obj):
        self.layout.prop(pinned_obj.cloudrig_prefs, 'collection_ui_type', expand=True)

        if pinned_obj.cloudrig_prefs.collection_ui_type == 'CLOUDRIG':
            return draw_cloudrig_collections(self, context, pinned_obj)

    return bpy.types.DATA_PT_bone_collections.draw_bkp(self, context)


#######################################
############## Hotkeys ################
#######################################


class CLOUDRIG_PT_hotkeys_panel(CLOUDRIG_PT_base):
    bl_idname = "CLOUDRIG_PT_hotkeys_panel"
    bl_label = "Hotkeys"

    cloudrig_keymap_items: dict[int, tuple["KeyConfig", "KeyMap", "KeyMapItem"]] = {}

    def draw(self, context):
        type(self).draw_hotkey_list(self.layout.column(), context)

    @classmethod
    def draw_hotkey_list(cls, layout, context):
        hotkey_class = cls
        user_kc = context.window_manager.keyconfigs.user

        keymap_data = list(hotkey_class.cloudrig_keymap_items.items())
        keymap_data = sorted(keymap_data, key=lambda tup: tup[1][2].name)

        prev_kmi = None
        for kmi_hash, kmi_tup in keymap_data:
            addon_kc, addon_km, addon_kmi = kmi_tup

            user_km = user_kc.keymaps.get(addon_km.name)
            if not user_km:
                # This really shouldn't happen.
                continue
            user_kmi = hotkey_class.find_kmi_in_km_by_hash(user_km, kmi_hash)

            col = layout.column()
            col.context_pointer_set("keymap", user_km)
            if user_kmi and prev_kmi and prev_kmi.name != user_kmi.name:
                col.separator()
            user_row = col.row()

            if False:
                # Debug code: Draw add-on and user KeyMapItems side-by-side.
                split = user_row.split(factor=0.5)
                addon_row = split.row()
                user_row = split.row()
                hotkey_class.draw_kmi(addon_km, addon_kmi, addon_row)
            if not user_kmi:
                # This should only happen for one frame during Reload Scripts.
                print(
                    "CloudRig: Can't find this hotkey to draw: ",
                    addon_kmi.name,
                    addon_kmi.to_string(),
                    kmi_hash,
                )
                continue

            hotkey_class.draw_kmi(user_km, user_kmi, user_row)
            prev_kmi = user_kmi

    @staticmethod
    def draw_kmi(km, kmi, layout):
        """A simplified version of draw_kmi from rna_keymap_ui.py."""

        map_type = kmi.map_type

        col = layout.column()

        split = col.split(factor=0.7)

        # header bar
        row = split.row(align=True)
        row.prop(kmi, "active", text="", emboss=False)
        km_name = km.name
        if km_name == 'Armature':
            km_name = 'Armature Edit'
        row.label(text=f'{kmi.name} ({km_name})')

        row = split.row(align=True)
        sub = row.row(align=True)
        sub.enabled = kmi.active
        sub.prop(kmi, "type", text="", full_event=True)

        if kmi.is_user_modified:
            row.operator(
                "preferences.keyitem_restore", text="", icon='BACK'
            ).item_id = kmi.id

    @staticmethod
    def print_kmi(kmi):
        idname = kmi.idname
        keys = kmi.to_string()
        props = str(list(kmi.properties.items()))
        print(idname, props, keys)

    @staticmethod
    def find_kmi_in_km_by_hash(keymap, kmi_hash):
        """There's no solid way to match modified user keymap items to their
        add-on equivalent, which is necessary to draw them in the UI reliably.

        To remedy this, we store a hash in the KeyMapItem's properties.

        This function lets us find a KeyMapItem with a stored hash in a KeyMap.
        Eg., we can pass a User KeyMap and an Addon KeyMapItem's hash, to find the
        corresponding user keymap, even if it was modified.

        The hash value is unfortunately exposed to the users, so we just hope they don't touch that.
        """

        for kmi in keymap.keymap_items:
            if not kmi.properties:
                continue
            if 'hash' not in kmi.properties:
                continue

            if kmi.properties['hash'] == kmi_hash:
                return kmi


def register_hotkey(
    bl_idname, hotkey_kwargs, *, key_cat='Window', space_type='EMPTY', op_kwargs={}
):
    """This function inserts a 'hash' into the created KeyMapItems' properties,
    so they can be compared to each other, and duplicates can be avoided."""

    wm = bpy.context.window_manager
    addon_keyconfig = wm.keyconfigs.addon
    if not addon_keyconfig:
        # This happens when running Blender in background mode.
        return

    # We limit the hash to a few digits, otherwise it errors when trying to store it.
    kmi_hash = (
        hash(json.dumps([bl_idname, hotkey_kwargs, key_cat, space_type, op_kwargs]))
        % 1000000
    )

    # If it already exists, don't create it again.
    for (
        existing_kmi_hash,
        existing_kmi_tup,
    ) in bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.items():
        existing_addon_kc, existing_addon_km, existing_kmi = existing_kmi_tup
        if kmi_hash == existing_kmi_hash:
            # The hash we just calculated matches one that is in storage.
            user_kc = wm.keyconfigs.user
            user_km = user_kc.keymaps.get(existing_addon_km.name)
            # NOTE: It's possible on Reload Scripts that some KeyMapItems remain in storage,
            # but are unregistered by Blender for no reason.
            # I noticed this particularly in the Weight Paint keymap.
            # So it's not enough to check if a KMI with a hash is in storage, we also need to check if a corresponding user KMI exists.
            user_kmi = CLOUDRIG_PT_hotkeys_panel.find_kmi_in_km_by_hash(
                user_km, kmi_hash
            )
            if user_kmi:
                # print("Hotkey already exists, skipping: ", existing_kmi.name, existing_kmi.to_string(), kmi_hash)
                return

    # print("Registering hotkey: ", bl_idname, hotkey_kwargs, key_cat)

    addon_keymaps = addon_keyconfig.keymaps
    addon_km = addon_keymaps.get(key_cat)
    if not addon_km:
        addon_km = addon_keymaps.new(name=key_cat, space_type=space_type)

    addon_kmi = addon_km.keymap_items.new(bl_idname, **hotkey_kwargs)
    for key in op_kwargs:
        value = op_kwargs[key]
        setattr(addon_kmi.properties, key, value)

    addon_kmi.properties['hash'] = kmi_hash

    bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items[kmi_hash] = (
        addon_keyconfig,
        addon_km,
        addon_kmi,
    )
    # print("CloudRig: Registered Hotkey: ", addon_kmi.idname, addon_kmi.to_string(), kmi_hash)


#######################################
############## Register ###############
#######################################

classes = (
    CloudRig_UIElement,
    CloudRig_RigPreferences,
    CloudRigBoneCollection,
    CLOUDRIG_UL_collections,
    CLOUDRIG_PT_settings,
    CLOUDRIG_PT_custom_ui,
    CLOUDRIG_PT_hotkeys_panel,
    CLOUDRIG_PT_collections_sidebar,
    CLOUDRIG_PT_collections_filter,
    CLOUDRIG_MT_collections_specials,
    CLOUDRIG_MT_collections_quick_select,
    POSE_OT_cloudrig_switch_parent_bake,
    POSE_OT_cloudrig_snap_bake,
    POSE_OT_cloudrig_toggle_ikfk_bake,
    POSE_OT_cloudrig_keyframe_all_settings,
    POSE_OT_cloudrig_reset,
    POSE_OT_cloudrig_collections_reveal_all,
    POSE_OT_cloudrig_collection_select,
    POSE_OT_cloudrig_collection_delete,
    POSE_OT_cloudrig_collection_add,
    POSE_OT_cloudrig_reorder_collections,
    POSE_OT_cloudrig_collection_assign,
    POSE_OT_cloudrig_collection_clipboard_copy,
    POSE_OT_cloudrig_collection_clipboard_paste,
    ARMATURE_OT_bone_collections_popup,
)


def is_registered(cls):
    """Returns whether a BPy class is registered.
    May not always work, needs more testing..."""
    # NOTE: For Operators, this is tricky!
    # It will work, but ONLY if you adhere perfectly to Blender's operator class
    # naming conventions!
    # If an operator's bl_idname is `pose.my_operator`, its registered bpy.type will be called
    # `POSE_OT_my_operator`, NO MATTER WHAT THE ACTUAL CLASS NAME YOU DEFINED WAS!
    if hasattr(bpy.types, cls.__name__):
        bl_type = getattr(bpy.types, cls.__name__)
        if bl_type and hasattr(bl_type, 'is_registered') and bl_type.is_registered:
            return bl_type
    if issubclass(cls, bpy.types.PropertyGroup):
        existing = bpy.types.PropertyGroup.bl_rna_get_subclass_py(cls.__name__)
        if existing and existing.is_registered:
            return existing
    if issubclass(cls, bpy.types.AddonPreferences):
        subclasses = bpy.types.AddonPreferences.__subclasses__()
        if cls in subclasses and cls.is_registered:
            return cls

    return False


def register():
    """Runs on rig generation, add-on registration, or when this file is executed
    via the text editor.
    Should be able to run without errors even if things are already registered.
    """

    # It's necessary to call unregister() in case a user
    # opens a .blend file where cloudrig.py is registered, then they try to
    # enable the CloudRig add-on.
    # The unregister() function already needs to be safe, so it can be called
    # even when there's nothing to unregister.
    unregister()

    for c in classes:
        if not is_registered(c):
            register_class(c)

    bpy.types.Object.cloudrig_prefs = PointerProperty(
        type=CloudRig_RigPreferences, override={'LIBRARY_OVERRIDABLE'}
    )
    bpy.types.Object.cloudrig_ui = CollectionProperty(type=CloudRig_UIElement)

    bpy.types.BoneCollection.cloudrig_info = PointerProperty(
        type=CloudRigBoneCollection, override={'LIBRARY_OVERRIDABLE'}
    )

    # Inject our custom Bone Collections panel.
    if not hasattr(bpy.types.DATA_PT_bone_collections, 'draw_bkp'):
        bpy.types.DATA_PT_bone_collections.draw_bkp = (
            bpy.types.DATA_PT_bone_collections.draw
        )
        bpy.types.DATA_PT_bone_collections.draw = builtin_collections_draw_override

    register_hotkey(
        bl_idname='wm.call_menu',
        hotkey_kwargs={
            'type': 'W',
            'value': 'PRESS',
            'shift': True,
            'alt': True,
        },
        key_cat='Pose',
        op_kwargs={'name': CLOUDRIG_MT_collections_quick_select.bl_idname},
    )

    for key_cat, space_type in {
        ('Pose', 'VIEW_3D'),
        ('Weight Paint', 'EMPTY'),
        ('Armature', 'EMPTY'),
    }:
        register_hotkey(
            bl_idname='armature.bone_collections_popup',
            hotkey_kwargs={'type': "M", 'value': "PRESS", 'shift': True},
            key_cat=key_cat,
            space_type=space_type,
        )


def unregister_hotkeys():
    if hasattr(bpy.types, 'CLOUDRIG_PT_hotkeys_panel'):
        for (
            kmi_hash,
            kmi_tup,
        ) in bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items.items():
            kc, km, kmi = kmi_tup
            km.keymap_items.remove(kmi)
        bpy.types.CLOUDRIG_PT_hotkeys_panel.cloudrig_keymap_items = {}
    print("CloudRig: Unregistered Hotkeys.")


def unregister():
    """Runs before register() on generation and when executed from the text editor.
    Should be able to run without errors even before there's anything to unregister.
    """

    # TODO: This also unregisters add-on hotkeys, which we don't want when this script
    # is executed via the text editor. Need to categorize the hotkeys somehow, and un-register
    # according to execution context!
    # unregister_hotkeys()

    try:
        del bpy.types.Object.cloudrig_prefs
        del bpy.types.BoneCollection.cloudrig_info
    except AttributeError:
        pass

    for c in classes:
        reg = is_registered(c)
        if reg:
            try:
                unregister_class(reg)
            except RuntimeError as e:
                print("Failed to unregister ", c.__name__, str(e))
                pass

    try:
        # Un-inject our collection UI override.
        bpy.types.DATA_PT_bone_collections.draw = (
            bpy.types.DATA_PT_bone_collections.draw_bkp
        )
        del bpy.types.DATA_PT_bone_collections.draw_bkp
    except:
        pass


if __name__ in ['__main__', 'builtins']:
    # __name__ == `CloudRig.generation.cloudrig` when executed by Blender python import statement.
    # We don't want to run in this case, since register() will be called explicitly by __init__.py.

    # __name__ == `__main__` when executed in Blender's Text Editor.
    # __name__ == `builtins` when executed by cloud_generator.

    register()
