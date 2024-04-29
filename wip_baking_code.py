import bpy
from bpy.types import Object, PoseBone, FCurve
import json
from bpy.props import StringProperty, IntProperty, BoolProperty
from mathutils import Matrix
from collections import OrderedDict


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
    def poll(cls, context) -> bool:
        rig = cls.get_context_rig(context)
        if not rig:
            return False
        return True

    @staticmethod
    def get_prop_target_value(prop_pb, prop_id) -> float:
        if prop_pb[prop_id] < 1.0:
            return 1.0
        return 0.0

    def get_properties_bone(self, rig: Object) -> PoseBone:
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

    @staticmethod
    def set_bone_selection(rig, select=False, pbones: list[PoseBone] = []):
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
            context.view_layer.update()
            pb = rig.pose.bones[bone_name]
            pb.matrix = mat.copy()


class SnapBakeOperator(SnappingOperator):
    do_bake: BoolProperty(name="Bake", default=False)
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")

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
        
        self.draw_affected_bones(layout, context)

    def draw_affected_bones(self, layout, context):
        rig = self.get_context_rig(context)
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def get_frame_range(self, context) -> list[int]:
        if not self.do_bake:
            return [context.scene.frame_current]

        return range(self.frame_start, self.frame_end + 1)

    @staticmethod
    def ensure_action(rig: Object):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.aciton = bpy.data.actions.new("ACT-" + rig.name)

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
    ):
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        return self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

    def keyframe_bones(
        self, context, frame_matrix_map: dict[int, dict[str, Matrix]], prop_pb: PoseBone
    ):
        rig = self.get_context_rig(context)
        pbones = [
            rig.pose.bones[name]
            for name in list(list(frame_matrix_map.values())[0].keys())
        ]

        # Deselect all bones, then reveal and select affected bones.
        self.set_bone_selection(rig, False)
        self.reveal_bones(pbones)
        self.set_bone_selection(rig, True, pbones)

        # Key original value and transforms at the start.
        context.scene.frame_set(self.frame_start)
        prop_pb.keyframe_insert(f'["{self.prop_id_name}"]', group=prop_pb.name)
        bpy.ops.anim.keyframe_insert()

        # Key original value and transforms at the end.
        context.scene.frame_set(self.frame_end)
        prop_pb.keyframe_insert(f'["{self.prop_id_name}"]', group=prop_pb.name)
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
                prop_pb.keyframe_insert(f'["{self.prop_id_name}"]', group=prop_pb.name)

                self.set_bone_matrices(context, rig, pbone_matrix_map)
                bpy.ops.anim.keyframe_insert()


class POSE_OT_cloudrig_bone_snap_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_bone_snap_bake"
    bl_label = "Snap & Bake Bones"
    bl_description = "Flip a custom property's value while preserving the world-matrix of some bones"

    def execute(self, context):
        return self.execute_bone_snap_bake(self, context)

    @staticmethod
    def execute_bone_snap_bake(self, context):
        rig = self.get_context_rig(context)
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
            self.keyframe_bones(context, frame_matrix_map, prop_pb)
        else:
            # Store (copies!) of world matrices.
            pbone_matrix_map = list(frame_matrix_map.values())[0]

            # Change property value.
            prop_pb[self.prop_id_name] = self.get_prop_target_value(
                prop_pb, self.prop_id_name
            )
            # Reveal & select affected bones.
            self.reveal_bones(affected_pbones)
            self.set_bone_selection(rig, True, affected_pbones)

            # Deselect all bones.
            self.set_bone_selection(rig, False)

            # Restore world matrices.
            self.set_bone_matrices(context, rig, pbone_matrix_map)

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

    def draw_affected_bones(self, layout, context):
        rig = self.get_context_rig(context)
        affected_pbones = self.get_affected_pbones(rig)
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for pbone in affected_pbones:
            bone_column.label(text=f"{' '*10} {pbone.name}")

    def invoke(self, context, _event):
        self.rig = self.get_context_rig(context)
        try:
            self.prop_pb = self.get_properties_bone(self.rig)
            self.current_value = self.prop_pb[self.prop_id_name]
            self.target_value = self.get_prop_target_value(self.prop_pb, self.prop_id_name)
            self.bone_map = self.get_bone_map(self.current_value)
        except Exception as exc:
            # NOTE: This doesn't show line number of the error.
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return super().invoke(context, _event)

    def execute(self, context):
        active_frame_bkp = context.scene.frame_current

        # Store (copies!) of world matrices.
        bones_to_snap = [self.rig.pose.bones[name] for name in self.bone_map.keys()]
        snap_to_bones = [self.rig.pose.bones[name] for name in self.bone_map.values()]
        frame_matrix_map = self.map_frames_to_bone_matrices(
            context, bones_to_snap, snap_to_bones
        )

        if self.do_bake:
            self.keyframe_bones(context, frame_matrix_map, self.prop_pb)
            context.scene.frame_set(active_frame_bkp)
            self.report({'INFO'}, "Finished baking.")
        else:
            # Change property value.
            self.prop_pb[self.prop_id_name] = self.get_prop_target_value(
                self.prop_pb, self.prop_id_name
            )

            # Deselect all bones.
            self.set_bone_selection(self.rig, False)

            pbone_matrix_map = list(frame_matrix_map.values())[0]
            # Restore world matrices.
            self.set_bone_matrices(context, self.rig, pbone_matrix_map)

            # Reveal & select affected bones.
            if self.target_value == 1 and self.ik_pole:
                bones_to_snap.append(self.rig.pose.bones[self.ik_pole])
            self.reveal_bones(bones_to_snap)
            self.set_bone_selection(self.rig, True, bones_to_snap)

        self.report({'INFO'}, "Snapping complete.")
        return {'FINISHED'}

    def get_pole_target_matrix(self, ik_pole: PoseBone, fk_first: PoseBone) -> Matrix:
        """Find the matrix where the IK pole should be."""
        """ This is only accurate when the bone chain lies perfectly on a plane
            and the IK Pole Angle is divisible by 90.
            This should be the case for a correct IK chain!
        """
        mat = ik_pole.matrix.copy()
        # Ultra simple solution, we just project the upperarm FK bone an extra length.
        mat.translation = fk_first.tail  # + fk_first.vector
        return mat

    def map_single_frame_to_bone_matrices(
        self, context, frame_number, bones_to_snap, snap_to_bones
    ):
        context.scene.frame_set(frame_number)
        context.view_layer.update()

        pbone_matrix_map = self.get_pbone_matrix_map(bones_to_snap, snap_to_bones)

        if self.target_value == 1 and self.ik_pole:
            # Snap IK pole
            pole_pb = self.rig.pose.bones[self.ik_pole]
            fk_upperarm = snap_to_bones[1]
            pbone_matrix_map[pole_pb.name] = self.get_pole_target_matrix(
                pole_pb, fk_upperarm
            )

        return pbone_matrix_map

    def get_bone_map(self, ik_value: float) -> OrderedDict[str, str]:
        map_fk_to_ik = OrderedDict(json.loads(self.map_fk_to_ik))
        map_ik_to_fk = OrderedDict(json.loads(self.map_ik_to_fk))

        bone_map = map_fk_to_ik if ik_value == 1 else map_ik_to_fk

        return bone_map

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Snapped bones:")
        for from_bone, to_bone in self.bone_map.items():
            bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")

        if self.current_value < 1:
            bone_column.label(text=f"{' '*10} {self.ik_pole}")


bpy.utils.register_class(POSE_OT_cloudrig_bone_snap_bake)
bpy.utils.register_class(POSE_OT_cloudrig_bone_snap_bake_ikfk)
bpy.ops.pose.cloudrig_bone_snap_bake_ikfk('INVOKE_DEFAULT',
    map_fk_to_ik=json.dumps(
        [
            ('FK-UpperArm.L', 'IK-M-UpperArm.L'),
            ('FK-Forearm.L', 'IK-M-Forearm.L'),
            ('FK-Wrist.L', 'IK-Wrist.L'),
        ]
    ),
    map_ik_to_fk=json.dumps(
        [
            ('IK-Wrist.L', 'FK-Wrist.L'),
            ('IK-M-UpperArm.L', 'FK-UpperArm.L'),
        ]
    ),
    ik_pole='POLE-UpperArm.L',
    prop_bone_name="Properties",
    prop_id_name="ik_left_upperarm",
    do_bake=False,
    frame_start=29,
    frame_end=50,
)
