import bpy
from bpy.types import Object, PoseBone, FCurve
import json
from bpy.props import StringProperty, IntProperty, BoolProperty
from mathutils import Matrix
from collections import defaultdict, OrderedDict


class SnappingOperator:
    bone_names: StringProperty(
        name="Bone Names",
        description="A python list converted to a string with json.dumps(). The order of the bone names matters, as dependents should come after their dependencies (ie. children after parents)",
    )
    prop_bone_name: StringProperty(
        name="Property Bone Name",
        description="Name of the pose bone on the active object that should have a custom property named prop_id_name",
    )
    prop_id_name: StringProperty(
        name="Custom Property Name",
        description="Name of the custom property on the pose bone, which will be toggled by this operator",
    )

    @staticmethod
    def get_context_rig(context) -> Object | None:
        if context.pose_object:
            return context.pose_object

        if context.active_object.type == 'ARMATURE':
            return context.active_object

    @classmethod
    def poll(cls, context):
        rig = cls.get_context_rig(context)
        if not rig:
            return False
        return True

    @staticmethod
    def get_prop_target_value(prop_pb, prop_id) -> float:
        if prop_pb[prop_id] < 1.0:
            return 1.0
        return 0.0

    def get_properties_bone(self, rig):
        if self.prop_bone_name not in rig.pose.bones:
            raise Exception(f"Bone not found in rig: `{self.prop_bone_name}`.")

        prop_pb = rig.pose.bones[self.prop_bone_name]
        if self.prop_id_name not in prop_pb:
            raise Exception(
                f"Property `{self.prop_id_name}` not found in bone `{self.prop_bone_name}`."
            )

        target_value = self.get_prop_target_value(prop_pb, self.prop_id_name)
        if int(prop_pb[self.prop_id_name]) == target_value:
            raise Exception(
                f"Value of property `{self.prop_id_name}` is already {target_value}."
            )

        return prop_pb

    def get_affected_pbones(self, rig: Object) -> list[PoseBone]:
        affected_pbones = set()
        for bone_name in json.loads(self.bone_names):
            pb = rig.pose.bones.get(bone_name)
            if pb:
                affected_pbones.add(pb)
            else:
                raise Exception(f"Bone `{bone_name}` not found.")
        return affected_pbones

    @staticmethod
    def get_pbone_matrix_map(pbones: list[PoseBone]) -> dict[str, Matrix]:
        return {pb.name: pb.matrix.copy() for pb in pbones}

    @staticmethod
    def set_bone_selection(rig, select=False, pbones: list[PoseBone] = []):
        if not pbones:
            pbones = rig.pose.bones
        for pb in pbones:
            pb.bone.select = select

    @staticmethod
    def reveal_bones(pbones):
        for pb in pbones:
            if pb.bone.hide:
                pb.bone.hide = False
            if not any([coll.is_visible for coll in pb.bone.collections]):
                coll = pb.bone.collections[0]
                while coll:
                    coll.is_visible = True
                    coll = coll.parent

    def set_bone_matrices(self, context, rig, pbone_matrix_map: dict[str, Matrix]):
        for bone_name, mat in pbone_matrix_map.items():
            context.view_layer.update()
            pb = rig.pose.bones[bone_name]
            pb.matrix = mat.copy()


class POSE_OT_cloudrig_bone_snap(SnappingOperator, bpy.types.Operator):
    """Change a custom property value while preserving the transforms of a set of bones"""

    bl_idname = "pose.cloudrig_bone_snap"
    bl_label = "Snap Bones"

    @staticmethod
    def execute_bone_snap(self, context):
        rig = self.get_context_rig(context)
        try:
            prop_pb = self.get_properties_bone(rig)
            pbones_to_preserve = self.get_affected_pbones(rig)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        # Store (copies!) of world matrices.
        pbone_matrix_map = self.get_pbone_matrix_map(pbones_to_preserve)

        # Change property value.
        prop_pb[self.prop_id_name] = self.get_prop_target_value(prop_pb, self.prop_id_name)

        # Deselect all bones.
        self.set_bone_selection(rig, False)

        # Restore world matrices.
        self.set_bone_matrices(context, pbone_matrix_map)

        # Reveal & select affected bones.
        self.reveal_bones(pbones_to_preserve)
        self.set_bone_selection(rig, True, pbones_to_preserve)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def execute(self, context):
        return self.execute_bone_snap(self, context)


class SnapBakeOperator(SnappingOperator):
    do_bake: BoolProperty(name="Bake", default=False)
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")

    def invoke(self, context, _event):
        self.frame_start = context.scene.frame_start
        self.frame_start-= 1 # Due to a Blender bug, the first time a Python script tries to frame change + insert keyframe, it will fail...
        self.frame_end = context.scene.frame_end
        self.do_bake = True
        return self.execute(context)

    def get_frame_range(self):
        return range(self.frame_start, self.frame_end + 1)

    @staticmethod
    def ensure_action(rig):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.aciton = bpy.data.actions.new("ACT-" + rig.name)

    def map_bone_matrices_to_frames(
        self, context, pbones, frame_numbers: list[int] = []
    ) -> dict[int, dict[PoseBone, Matrix]]:
        if not frame_numbers:
            frame_numbers = self.get_frame_range()

        frame_matrix_map = defaultdict()
        for frame_number in frame_numbers:
            context.scene.frame_set(frame_number)
            context.view_layer.update()
            frame_matrix_map[frame_number] = self.get_pbone_matrix_map(pbones)

        return frame_matrix_map

    def keyframe_bones(
        self, context, frame_matrix_map: dict[int, dict[str, Matrix]], prop_pb: PoseBone
    ):
        rig = self.get_context_rig(context)
        pbones = [rig.pose.bones[name] for name in list(list(frame_matrix_map.values())[0].keys())]

        # Deselect all bones, then reveal and select affected bones.
        self.set_bone_selection(rig, False)
        self.reveal_bones(pbones)
        self.set_bone_selection(rig, True, pbones)

        # Key original value and transforms at the start.
        context.scene.frame_set(self.frame_start)
        prop_pb.keyframe_insert(
            f'["{self.prop_id_name}"]', group=prop_pb.name
        )
        bpy.ops.anim.keyframe_insert()

        # Key original value and transforms at the end.
        context.scene.frame_set(self.frame_end)
        prop_pb.keyframe_insert(
            f'["{self.prop_id_name}"]', group=prop_pb.name
        )
        bpy.ops.anim.keyframe_insert()

        # ViewLayer Update is necessary for some reason.
        target_value = self.get_prop_target_value(prop_pb, self.prop_id_name)
        # Idk why we have to go over them twice, but if we don't, we get issues 
        # at the start and end of the frame range.
        for i in range(2):
            for frame_number, pbone_matrix_map in frame_matrix_map.items():
                if frame_number in {self.frame_start, self.frame_end}:
                    continue
                context.scene.frame_set(frame_number)

                # Change & key property value.
                prop_pb[self.prop_id_name] = target_value
                prop_pb.keyframe_insert(
                    f'["{self.prop_id_name}"]', group=prop_pb.name
                )

                self.set_bone_matrices(context, rig, pbone_matrix_map)
                bpy.ops.anim.keyframe_insert()


class POSE_OT_cloudrig_bone_snap_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_bone_snap_bake"
    bl_label = "Snap & Bake Bones"

    def execute(self, context):
        return self.execute_bone_snap_bake(self, context)

    @staticmethod
    def execute_bone_snap_bake(self, context):
        if not self.do_bake:
            return POSE_OT_cloudrig_bone_snap.execute_bone_snap(self, context)

        rig = self.get_context_rig(context)
        try:
            prop_pb = self.get_properties_bone(rig)
            pbones_to_bake = self.get_affected_pbones(rig)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self.ensure_action(rig)

        active_frame_bkp = context.scene.frame_current

        # Save the matrix of each bone at each frame.
        frame_matrix_map = self.map_bone_matrices_to_frames(context, pbones_to_bake)

        # Restore world matrices.
        self.keyframe_bones(context, frame_matrix_map, prop_pb)

        context.scene.frame_set(active_frame_bkp)
        self.report({'INFO'}, "Finished baking.")
        return {'FINISHED'}


class POSE_OT_cloudrig_bone_snap_bake_ikfk(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_bone_snap_bake_ikfk"
    bl_label = "Snap & Bake Bones to Other Bones"

    map_fk_to_ik: StringProperty(
        description="List of tuples of (fk_bone, target_bone) for snapping FK to IK"
    )
    map_ik_to_fk: StringProperty(
        description="List of tuples of (ik_bone, target_bone) for snapping IK to FK"
    )
    ik_pole: StringProperty(
        description="Name of IK pole vector bone, for snapping IK to FK"
    )

    def get_pole_target_matrix(self, ik_pole: PoseBone, fk_first: PoseBone, fk_last: PoseBone) -> Matrix:
        """Find the matrix where the IK pole should be."""
        """ This is only accurate when the bone chain lies perfectly on a plane
            and the IK Pole Angle is divisible by 90.
            This should be the case for a correct IK chain!
        """
        chain_length = fk_first.vector.length + fk_last.vector.length

        mat = ik_pole.matrix.copy()
        # Ultra simple and precise solution, just not centered, but who cares.
        mat.translation = fk_first.tail + (fk_first.tail-fk_first.head).normalized() * chain_length/2
        return mat

    def execute(self, context):
        rig = self.get_context_rig(context)
        try:
            prop_pb = self.get_properties_bone(rig)
            current_value = prop_pb[self.prop_id_name]
            target_value = self.get_prop_target_value(prop_pb, self.prop_id_name)
            bone_map = self.get_bone_map(rig, current_value)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        # Store (copies!) of world matrices.
        target_pbones = [rig.pose.bones[bn] for bn in bone_map.values()]
        pbone_matrix_map = self.get_pbone_matrix_map(target_pbones)
        pbone_matrix_map = OrderedDict([
            (bone_name, pbone_matrix_map[bone_map[bone_name]]) for bone_name, mat in bone_map.items()
        ])

        # Change property value.
        prop_pb[self.prop_id_name] = self.get_prop_target_value(prop_pb, self.prop_id_name)

        # Deselect all bones.
        self.set_bone_selection(rig, False)

        if target_value == 1 and self.ik_pole:
            # Snap IK pole
            pole_pb = rig.pose.bones[self.ik_pole]
            fk_first = target_pbones[0]
            fk_last = target_pbones[1]
            pbone_matrix_map[pole_pb.name] = self.get_pole_target_matrix(fk_first, fk_last, pole_pb)

        # Restore world matrices.
        self.set_bone_matrices(context, rig, pbone_matrix_map)

        # Reveal & select affected bones.
        affected_pbones = [rig.pose.bones[bn] for bn in list(pbone_matrix_map.keys())]
        self.reveal_bones(affected_pbones)
        self.set_bone_selection(rig, True, affected_pbones)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def get_bone_map(self, rig: Object, ik_value: float) -> OrderedDict[str, str]:
        map_fk_to_ik = OrderedDict(json.loads(self.map_fk_to_ik))
        map_ik_to_fk = OrderedDict(json.loads(self.map_ik_to_fk))

        bone_map = map_fk_to_ik if ik_value == 1 else map_ik_to_fk

        return bone_map

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Snapped bones:")
        for from_bone, to_bone in self.get_bone_map(context):
            bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")


bpy.utils.register_class(POSE_OT_cloudrig_bone_snap)
bpy.utils.register_class(POSE_OT_cloudrig_bone_snap_bake)
bpy.utils.register_class(POSE_OT_cloudrig_bone_snap_bake_ikfk)
bpy.ops.pose.cloudrig_bone_snap_bake_ikfk(
    map_fk_to_ik=json.dumps([
        ('FK-UpperArm.L', 'IK-M-UpperArm.L'), 
        ('FK-Forearm.L', 'IK-M-Forearm.L'), 
        ('FK-Wrist.L', 'IK-Wrist.L'),
    ]),
    map_ik_to_fk=json.dumps([
        ('IK-Wrist.L', 'FK-Wrist.L'),
        ('IK-M-UpperArm.L', 'FK-UpperArm.L'),
    ]),

    ik_pole = 'POLE-UpperArm.L',

    prop_bone_name="Properties",
    prop_id_name = "ik_left_upperarm",

    do_bake=True,
    frame_start=29,
    frame_end=50
)
