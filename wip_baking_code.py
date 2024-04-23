import bpy
from bpy.types import Object, PoseBone, FCurve
import json
from bpy.props import StringProperty, IntProperty, BoolProperty
from mathutils import Matrix
from collections import defaultdict

class SnappingOperator:
    bone_names: StringProperty(
        name="Bone Names",
        description="A python list converted to a string with json.dumps(). The order of the bone names matters, as dependents should come after their dependencies (ie. children after parents)"
    )
    prop_bone_name: StringProperty(
        name="Property Bone Name",
        description="Name of the pose bone on the active object that should have a custom property named prop_id_name"
    )
    prop_id_name: StringProperty(
        name="Custom Property Name",
        description="Name of the custom property on the pose bone, which will be toggled by this operator"
    )
    prop_target_value: IntProperty(
        name="Property Target Value",
        description="The value the property should have after this operator has run. If that is already its value, this operator won't do anything"
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

    def get_properties_bone(self, rig):
        if self.prop_bone_name not in rig.pose.bones:
            raise Exception(f"Bone not found in rig: `{self.prop_bone_name}`.")

        prop_pb = rig.pose.bones[self.prop_bone_name]
        if self.prop_id_name not in prop_pb:
            raise Exception(f"Property `{self.prop_id_name}` not found in bone `{self.prop_bone_name}`.")

        if int(prop_pb[self.prop_id_name]) == self.prop_target_value:
            raise Exception(f"Value of property `{self.prop_id_name}` is already {self.prop_target_value}.")

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
    def get_pbone_matrix_map(pbones: list[PoseBone]) -> dict[PoseBone, Matrix]:
        return {pb : pb.matrix.copy() for pb in pbones}

    @staticmethod
    def set_bone_selection(rig, select=False, pbones: list[PoseBone]=[]):
        if not pbones:
            pbones = rig.pose.bones
        for pb in pbones:
            pb.bone.select = select
    
    @staticmethod
    def reveal_bones(pbones):
        for pb in pbones:
            if pb.bone.hide:
                pb.bone.hide=False
            if not any([coll.is_visible for coll in pb.bone.collections]):
                coll = pb.bone.collections[0]
                while coll:
                    coll.is_visible = True
                    coll = coll.parent

    def set_bone_matrices(self, pbone_matrix_map: dict[PoseBone, Matrix]):
        # NOTE: Make sure view layer is updated before this function is called.
        for pb, mat in pbone_matrix_map.items():
            pb.matrix = mat


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
        prop_pb[self.prop_id_name] = self.prop_target_value

        # Deselect all bones.
        self.set_bone_selection(rig, False)

        # Restore world matrices.
        # ViewLayer Update is necessary for some reason.
        context.view_layer.update()
        self.set_bone_matrices(pbone_matrix_map)

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
        self.frame_end = context.scene.frame_end
        self.do_bake = True
        return self.execute(context)

    @staticmethod
    def ensure_action(rig):
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.aciton = bpy.data.actions.new("ACT-" + rig.name)


class POSE_OT_cloudrig_bone_snap_bake(SnapBakeOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_bone_snap_bake"
    bl_label = "Snap & Bake Bones"

    def execute(self, context):
        self.execute_bone_snap_bake(self, context)

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

        frame_numbers = range(self.frame_start, self.frame_end+1)

        # Save the matrix of each bone at each frame.
        frame_matrix_map = defaultdict()
        for frame_number in frame_numbers:
            context.scene.frame_set(frame_number)
            frame_matrix_map[frame_number] = self.get_pbone_matrix_map(pbones_to_bake)

        # Change property value.
        prop_pb[self.prop_id_name] = self.prop_target_value

        # Deselect all bones, then reveal and select affected bones.
        self.set_bone_selection(rig, False)
        self.reveal_bones(pbones_to_bake)
        self.set_bone_selection(rig, True, pbones_to_bake)

        # Restore world matrices.
        # ViewLayer Update is necessary for some reason.
        context.view_layer.update()
        for frame_number, pbone_matrix_map in frame_matrix_map.items():
            print("Baking Frame: ", frame_number)
            context.scene.frame_set(frame_number)
            self.set_bone_matrices(pbone_matrix_map)
            bpy.ops.anim.keyframe_insert()

        context.scene.frame_set(active_frame_bkp)
        self.report({'INFO'}, "Finished baking.")
        return {'FINISHED'}



class POST_OT_cloudrig_bone_snap_bake_map(SnappingOperator, bpy.types.Operator):
    bl_idname = "pose.cloudrig_bone_snap_bake_map"
    bl_label = "Snap & Bake Bones to Other Bones"

    map_on: StringProperty(description="Bone name dictionary to use when the property is toggled ON")
    map_off: StringProperty(description="Bone name dictionary to use when the property is toggled OFF")




















#######################################
############ Keyframe Baking ##########
#######################################

class SnapBakeOperator:
    """Change a custom property value, while ensuring certain bones do not move,
    and that these bones get keyed, optionally in a given frame range"""

    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    do_bake: BoolProperty(
        name="Bake Keyframes in Range",
        options={'SKIP_SAVE'},
        description="Bake keyframes for the affected bones and remove keyframes from the switched property",
        default=False,
    )
    frame_start: IntProperty(name="Start Frame")
    frame_end: IntProperty(name="End Frame")
    bake_every_frame: BoolProperty(
        name="Bake Every Frame",
        description="Insert a keyframe on every frame of the affected bones, rather than only frames which are keyframed on the source bones. Results in a more accurate bake, but takes longer and is harder to edit afterwards",
        default=True,
    )

    bones: StringProperty(name="Control Bones")
    prop_bone: StringProperty(name="Property Bone")
    prop_id: StringProperty(name="Property")
    prop_value: IntProperty(
        name="Property Value",
        description="If the property value is already set to this, the operator will do nothing.",
        default=-1,
    )

    select_bones: BoolProperty(name="Select Affected Bones", default=True)

    @classmethod
    def poll(cls, context):
        return context.pose_object

    def execute_scan_curves(self, context, obj):
        "Register frames to be baked, and return curves that should be cleared."
        if self.bake_every_frame:
            self.bake_frames_raw = [i for i in range(self.frame_start, self.frame_end)]
        else:
            self.bake_add_bone_frames(self.bone_names)
        return None

    def set_selection(self, context, bones):
        if self.select_bones:
            for b in context.selected_pose_bones:
                b.bone.select = False
            for b in bones:
                b.bone.select = True

    def invoke(self, context, event):
        self.init_invoke(context)

        if hasattr(self, 'draw'):
            return context.window_manager.invoke_props_dialog(self)
        else:
            return context.window_manager.invoke_confirm(self, event)

    def init_invoke(self, context):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        self.bone_names = json.loads(self.bones)

    def init_execute(self, context):
        pass

    def prop_value_matches(self):
        prop_value = get_custom_property_value(
            self.bake_rig, self.prop_bone, self.prop_id
        )
        return self.prop_value == prop_value

    def execute(self, context):
        self.init_execute(context)
        self.init_bake(context)

        if self.prop_value_matches():
            return {'CANCELLED'}

        curves = self.execute_scan_curves(context, self.bake_rig)

        if self.do_bake and self.report_bake_empty():
            return {'CANCELLED'}

        try:
            save_state = self.bake_save_state(context)

            context.scene.frame_set(range[0])
            range = self.get_bake_range()
            range_raw = self.nla_to_raw(range)
            range, range_raw = delete_curve_keys_in_range(
                curves, range_raw[0], range_raw[1]
            )

            self.execute_before_apply(context, self.bake_rig, range, range_raw)

            self.bake_apply_state(context, save_state)

        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, 'Exception: ' + str(e))

        return {'FINISHED'}

    # Default behavior implementation
    def init_bake(self, context):
        if not self.do_bake:
            return
        self.bake_rig = context.active_object
        self.bake_anim = self.bake_rig.animation_data
        self.bake_curve_table = FCurveTable(self.bake_rig.animation_data.action)
        self.bake_current_frame = context.scene.frame_current
        self.bake_frames_raw = set()

        self.keyflags = get_keying_flags(context)
        self.keyflags_switch = None

        if False:  # context.window_manager.rigify_transfer_use_all_keys:
            self.bake_add_curve_frames(self.bake_curve_table.curve_map)

    def execute_scan_curves(self, context, obj):
        "Override to register frames to be baked, and return curves that should be cleared."
        raise NotImplementedError()

    def bake_save_state(self, context) -> Dict[int, Tuple[List[Matrix], List[Vector]]]:
        "Scans frames and collects data for baking before changing anything."
        rig = self.bake_rig
        scene = context.scene

        save_state = dict()

        try:
            self.before_save_state(context, rig)

            for frame in self.bake_frames:
                scene.frame_set(frame)
                save_state[frame] = self.save_frame_state(context, rig)

        finally:
            self.after_save_state(context, rig)

        return save_state

    def execute_before_apply(self, context, obj, range, range_raw):
        "Override to execute code one time before the bake apply frame scan."
        pass

    def bake_apply_state(
        self, context, save_state: Dict[int, Tuple[List[Matrix], List[Vector]]]
    ):
        "Scans frames and applies the baking operation."
        rig = self.bake_rig
        scene = context.scene

        for frame in self.bake_frames:
            scene.frame_set(frame)
            self.apply_frame_state(context, rig, save_state.get(frame))

        clean_action_empty_curves(self.bake_rig.animation_data.action)
        scene.frame_set(self.bake_current_frame)

    # Utilities

    def bake_get_bone(self, bone_name):
        "Get pose bone by name."
        return self.bake_rig.pose.bones[bone_name]

    def bake_get_bones(self, bone_names):
        "Get multiple pose bones by name."
        if isinstance(bone_names, (list, set)):
            return [self.bake_get_bone(name) for name in bone_names]
        else:
            return self.bake_get_bone(bone_names)

    def bake_get_all_bone_curves(self, bone_names, props):
        "Get a list of all curves for the specified properties of the specified bones."
        return list(
            self.bake_curve_table.list_all_prop_curves(
                self.bake_get_bones(bone_names), props
            )
        )

    def bake_get_all_bone_custom_prop_curves(self, bone_names, props):
        "Get a list of all curves for the specified custom properties of the specified bones."
        return self.bake_get_all_bone_curves(
            bone_names, [rna_idprop_quote_path(p) for p in props]
        )

    def bake_get_bone_prop_curves(self, bone_name, prop):
        "Get an index to curve dict for the specified property of the specified bone."
        return self.bake_curve_table.get_prop_curves(
            self.bake_get_bone(bone_name), prop
        )

    def bake_get_bone_custom_prop_curves(self, bone_name, prop):
        "Get an index to curve dict for the specified custom property of the specified bone."
        return self.bake_curve_table.get_custom_prop_curves(
            self.bake_get_bone(bone_name), prop
        )

    def bake_add_curve_frames(self, curves):
        "Register frames keyed in the specified curves for baking."
        self.bake_frames_raw |= get_curve_frame_set(curves, self.bake_frame_range_raw)

    def bake_add_bone_frames(self, bone_names, props=TRANSFORM_PROPS_ALL):
        "Register frames keyed for the specified properties of the specified bones for baking."
        curves = self.bake_get_all_bone_curves(bone_names, props)
        self.bake_add_curve_frames(curves)
        return curves

    def bake_replace_custom_prop_keys_constant(self, bone, prop, new_value):
        "If the property is keyframed, delete keys in bake range and re-key as Constant."
        prop_curves = self.bake_get_bone_custom_prop_curves(bone, prop)

        if prop_curves and 0 in prop_curves:
            range_raw = self.nla_to_raw(self.get_bake_range())
            delete_curve_keys_in_range(prop_curves, range_raw)
            set_custom_property_value(
                self.bake_rig, bone, prop, new_value, keyflags={'INSERTKEY_AVAILABLE'}
            )
            set_curve_key_interpolation(prop_curves, 'CONSTANT', range_raw)

    def bake_add_frames_done(self):
        "Computes and sets the final set of frames to bake."
        frames = self.nla_from_raw(self.bake_frames_raw)
        self.bake_frames = sorted(set(map(round, frames)))

    def nla_from_raw(self, frames):
        "Convert frame(s) from inner action time to scene time."
        return nla_tweak_to_scene(self.bake_anim, frames)

    def nla_to_raw(self, frames):
        "Convert frame(s) from scene time to inner action time."
        return nla_tweak_to_scene(self.bake_anim, frames, invert=True)

    def is_bake_empty(self):
        return len(self.bake_frames_raw) == 0

    def report_bake_empty(self):
        self.bake_add_frames_done()
        if self.is_bake_empty():
            self.report({'WARNING'}, 'No keys to bake.')
            return True
        return False

    def get_bake_range(self):
        "Returns the frame range that is being baked."
        if self.bake_frame_range:
            return self.bake_frame_range
        else:
            frames = self.bake_frames
            return (frames[0], frames[-1])

class POSE_OT_cloudrig_snap_bake(SnapBakeOperator, bpy.types.Operator):
    """Toggle a custom property while ensuring that some bones stay in place"""

    bl_idname = "pose.cloudrig_snap_bake"
    bl_label = "Snap And Bake Bones"

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Affected bones:")
        for b in self.bone_names:
            bone_column.label(text=f"{' '*10} {b}")
        # bone_column.label(text=f"Affected property:")
        # bone_column.label(text=f'    pose.bones["{self.prop_bone}"]["{self.prop_id}"]')

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
            col.row().prop(self, 'bake_every_frame')

        self.draw_affected_bones(layout, context)

    def execute(self, context):
        rig = context.pose_object or context.active_object
        self.keyflags = get_autokey_flags(context, ignore_keyset=True)
        self.keyflags_switch = add_flags_if_set(self.keyflags, {'INSERTKEY_AVAILABLE'})

        ret = {'FINISHED'}
        if self.do_bake:
            ret = super().execute(context)
        else:
            self.init_execute(context)
            self.init_bake(context)

            if self.prop_value_matches():
                return {'CANCELLED'}

            try:
                frame_state = self.save_frame_state(context, rig)
                self.after_save_state(context, rig)
                self.apply_frame_state(context, rig, frame_state)

            except Exception as e:
                traceback.print_exc()
                self.report({'ERROR'}, 'Exception: ' + str(e))

        bones = get_bones(rig, self.bones)
        self.set_selection(context, bones)

        return ret

    def save_frame_state(
        self, context, rig, bone_names=None
    ) -> Tuple[List[Matrix], List[Vector]]:
        """Return the Pose Space matrices of the affected bones so they can be restored later."""
        if not bone_names:
            bone_names = self.bone_names

        matrices = []
        scales = []
        for bn in bone_names:
            pb = rig.pose.bones.get(bn)
            assert pb, "Bone does not exist: " + bn
            matrices.append(pb.matrix.copy())
            scales.append(pb.scale.copy())

        return matrices, scales

    def after_save_state(self, context, rig):
        """After saving the bone matrices, it's time to set the property value.
        It is expected that the rig has drivers which causes this property value
        change to affect the bones' transforms."""
        value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
        if self.do_bake:
            # If we want the snapping to affect existing animation, rather than just the current pose.
            any_curves_on_property = self.bake_get_bone_prop_curves(
                self.prop_bone, f'["{self.prop_id}"]'
            )
            if any_curves_on_property:
                self.bake_replace_custom_prop_keys_constant(
                    self.prop_bone, self.prop_id, 1 - value
                )
        else:
            set_custom_property_value(
                rig,
                self.prop_bone,
                self.prop_id,
                1 - value,
                keyflags=self.keyflags_switch,
            )
        context.view_layer.update()

    def apply_frame_state(
        self, context, rig, save_state: Tuple[List[Matrix], List[Vector]]
    ):
        """Set the transform matrices of the bones to their saved state."""
        matrices, scales = save_state
        for i, bone_name in enumerate(self.bone_names):
            old_matrix = matrices[i]
            set_transform_from_matrix(
                context,
                rig,
                bone_name,
                old_matrix,
            )
            pb = rig.pose.bones.get(bone_name)
            # TODO: For some reason, reading and writing the matrix can result in
            # significant changes to local scale, even when nothing is scaled.
            # So, just keep a copy of the local scale and restore it after applying the matrix.
            pb.scale = scales[i]

            context.evaluated_depsgraph_get().update()  # This matters!!!!

class POSE_OT_cloudrig_switch_parent_bake(POSE_OT_cloudrig_snap_bake):
    """Extend POSE_OT_cloudrig_snap_bake with a parent selector"""

    bl_idname = "pose.cloudrig_switch_parent_bake"
    bl_label = "Apply Switch Parent To Keyframes"
    bl_description = "Switch parent over a frame range, adjusting keys to preserve the bone position and orientation"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    parent_names: StringProperty(name="Parent Names")

    def parent_items(self, context):
        parents = json.loads(self.parent_names)
        items = [(str(i), name, name) for i, name in enumerate(parents)]
        return items

    selected: EnumProperty(name="Selected Parent", items=parent_items)

    def draw(self, context):
        self.layout.prop(self, 'selected', text='')
        super().draw(context)

    def after_save_state(self, context, rig):
        """After saving the bone matrices, it's time to set the property value."""
        # value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
        if self.do_bake:
            self.bake_replace_custom_prop_keys_constant(
                self.prop_bone, self.prop_id, int(self.selected)
            )
        else:
            set_custom_property_value(
                rig,
                self.prop_bone,
                self.prop_id,
                int(self.selected),
                keyflags=self.keyflags_switch,
            )
        context.view_layer.update()

class POSE_OT_cloudrig_snap_mapped_bake(POSE_OT_cloudrig_snap_bake):
    """Extend POSE_OT_cloudrig_snap_bake with the ability to snap a list of bones
    to another (equal length) list of bones.
    """

    bl_idname = "pose.cloudrig_snap_mapped_bake"
    bl_label = "Snap And Bake Bones (Mapped)"
    bl_description = "Toggle a custom property and snap some bones to some other bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    map_on: (
        StringProperty()
    )  # Bone name dictionary to use when the property is toggled ON.
    map_off: (
        StringProperty()
    )  # Bone name dictionary to use when the property is toggled OFF.

    hide_on: StringProperty()  # List of bone names to hide when property is toggled ON.
    hide_off: (
        StringProperty()
    )  # List of bone names to hide when property is toggled OFF.

    def init_invoke(self, context):
        rig = context.pose_object or context.active_object
        value = get_custom_property_value(rig, self.prop_bone, self.prop_id)

        map_on = json.loads(self.map_on)
        map_off = json.loads(self.map_off)

        self.bone_map = map_off if value == 1 else map_on
        bone_names = [t[0] for t in self.bone_map]
        self.bones = json.dumps(bone_names)
        super().init_invoke(
            context
        )  # This creates self.bone_names based on self.bones.

    def draw_affected_bones(self, layout, context):
        bone_column = layout.column(align=True)
        bone_column.label(text="Snapped bones:")
        for from_bone, to_bone in self.bone_map:
            bone_column.label(text=f"{' '*10} {from_bone} -> {to_bone}")

    def save_frame_state(self, context, rig, bone_names=None) -> List[Matrix]:
        if not bone_names:
            bone_names = [t[1] for t in self.bone_map]
        return super().save_frame_state(context, rig, bone_names)

    def execute_scan_curves(self, context, obj):
        "Register frames to be baked, and return curves that should be cleared."

        if self.bake_every_frame:
            self.bake_frames_raw = [i for i in range(self.frame_start, self.frame_end)]
        else:
            bone_names = [t[1] for t in self.bone_map]
            self.bake_add_bone_frames(bone_names)
            bone_names = [t[0] for t in self.bone_map]
            self.bake_add_bone_frames(bone_names)
        return None

class POSE_OT_cloudrig_toggle_ikfk_bake(POSE_OT_cloudrig_snap_mapped_bake):
    """Extends POSE_OT_cloudrig_snap_mapped_bake with special treatment for the IK elbow"""

    bl_idname = "pose.cloudrig_toggle_ikfk_bake"
    bl_label = "Toggle And Bake IK/FK"
    bl_description = "Toggle a custom property and snap some bones to some other bones"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    ik_pole: StringProperty()
    fk_first: StringProperty()
    fk_last: StringProperty()

    def init_invoke(self, context):
        rig = context.active_object

        self.pole = rig.pose.bones.get(self.ik_pole)  # Can be None.
        prop_value = get_custom_property_value(rig, self.prop_bone, self.prop_id)
        self.is_pole = prop_value == 0 and self.pole != None

        super().init_invoke(context)

        if self.is_pole:
            self.bone_names.append(self.pole.name)
            self.bones = json.dumps(self.bone_names)

    def save_frame_state(
        self, context, rig, bone_names=None
    ) -> Tuple[List[Matrix], List[Vector]]:
        matrices, scales = super().save_frame_state(context, rig)
        if self.is_pole:
            matrices.append(self.get_pole_target_matrix())
            scales.append(rig.pose.bones.get(self.ik_pole).scale)

        return matrices, scales

    def get_pole_target_matrix(self):
        """Find the matrix where the IK pole should be."""
        """ This is only accurate when the bone chain lies perfectly on a plane
            and the IK Pole Angle is divisible by 90.
            This should be the case for a correct IK chain!
        """

        rig = self.bake_rig

        fk_first = rig.pose.bones.get(self.fk_first)
        fk_last = rig.pose.bones.get(self.fk_last)
        assert (
            fk_first and fk_last
        ), f"Can't calculate pole target location due to one of these FK bones missing: {self.fk_first}, {self.fk_last}"

        chain_length = fk_first.vector.length + fk_last.vector.length
        pole_distance = chain_length / 2

        pole_direction = (fk_first.vector - fk_last.vector).normalized()

        pole_loc = fk_first.tail + pole_direction * pole_distance

        mat = self.pole.matrix.copy()
        mat.translation = pole_loc
        return mat

def set_curve_key_interpolation(curves, ipo, key_range=None):
    "Assign the given interpolation value to all curve keys in range."
    for key in flatten_curve_key_set(curves, key_range):
        key.interpolation = ipo


def delete_curve_keys_in_range(curves: List[FCurve], frame_start: int, frame_end: int):
    "Delete all keys of the given curves within the given range."
    for curve in flatten_curve_set(curves):
        points = curve.keyframe_points
        for i in range(len(points), 0, -1):
            key = points[i - 1]
            if frame_start <= key.co[0] <= frame_end:
                points.remove(key, fast=True)
        curve.update()


def flatten_curve_set(curves):
    "Iterate over all FCurves inside a set of nested lists and dictionaries."
    if curves is None:
        pass
    elif isinstance(curves, bpy.types.FCurve):
        yield curves
    elif isinstance(curves, dict):
        for sub in curves.values():
            yield from flatten_curve_set(sub)
    else:
        for sub in curves:
            yield from flatten_curve_set(sub)


def flatten_curve_key_set(curves, key_range=None):
    "Iterate over all keys of the given fcurves in the specified range."
    for curve in flatten_curve_set(curves):
        for key in curve.keyframe_points:
            if key_range is None or key_range[0] <= key.co[0] <= key_range[1]:
                yield key


def get_curve_frame_set(curves, key_range=None):
    "Compute a set of all time values with existing keys in the given curves and range."
    return set(key.co[0] for key in flatten_curve_key_set(curves, key_range))


def clean_action_empty_curves(action):
    "Delete all empty curves from the given action."
    for curve in list(action.fcurves):
        if curve.is_empty:
            action.fcurves.remove(curve)
    action.update_tag()


TRANSFORM_PROPS_LOCATION = frozenset(['location'])
TRANSFORM_PROPS_ROTATION = frozenset(
    ['rotation_euler', 'rotation_quaternion', 'rotation_axis_angle']
)
TRANSFORM_PROPS_SCALE = frozenset(['scale'])
TRANSFORM_PROPS_ALL = frozenset(
    TRANSFORM_PROPS_LOCATION | TRANSFORM_PROPS_ROTATION | TRANSFORM_PROPS_SCALE
)


class FCurveTable(object):
    "Table for efficient lookup of FCurves by properties."

    def __init__(self, action):
        self.action = action
        self.curve_map = self.index_curves(self.action.fcurves)

    def index_curves(self, curves):
        curve_map = py_collections.defaultdict(dict)
        for curve in curves:
            index = curve.array_index
            if index < 0:
                index = 0
            curve_map[curve.data_path][index] = curve
        return curve_map

    def get_prop_curves(self, ptr, prop_path):
        "Returns a dictionary from array index to curve for the given property, or Null."
        return self.curve_map.get(ptr.path_from_id(prop_path))

    def list_all_prop_curves(self, ptr_set, path_set):
        "Iterates over all FCurves matching the given object(s) and properti(es)."
        if isinstance(ptr_set, bpy.types.bpy_struct):
            ptr_set = [ptr_set]
        for ptr in ptr_set:
            for path in path_set:
                curves = self.get_prop_curves(ptr, path)
                if curves:
                    yield from curves.values()

    def get_custom_prop_curves(self, ptr, prop):
        return self.get_prop_curves(ptr, rna_idprop_quote_path(prop))


def nla_tweak_to_scene(anim_data, frames, invert=False):
    "Convert a frame value or list between scene and tweaked NLA strip time."
    if frames is None:
        return None
    elif anim_data is None or not anim_data.use_tweak_mode:
        return frames
    elif isinstance(frames, (int, float)):
        return anim_data.nla_tweak_strip_time_to_scene(frames, invert=invert)
    else:
        return type(frames)(
            anim_data.nla_tweak_strip_time_to_scene(v, invert=invert) for v in frames
        )


def add_flags_if_set(base, new_flags):
    "Add more flags if base is not None."
    if base is None:
        return None
    else:
        return base | new_flags


def get_keying_flags(context):
    "Retrieve the general keyframing flags from user preferences."
    prefs = context.preferences
    ts = context.scene.tool_settings
    flags = set()
    # Not adding INSERTKEY_VISUAL
    if prefs.edit.use_keyframe_insert_needed:
        flags.add('INSERTKEY_NEEDED')
    if ts.use_keyframe_cycle_aware:
        flags.add('INSERTKEY_CYCLE_AWARE')
    return flags


def get_autokey_flags(context, ignore_keyset=False):
    "Retrieve the Auto Keyframe flags, or None if disabled."
    ts = context.scene.tool_settings
    if ts.use_keyframe_insert_auto and (
        ignore_keyset or not ts.use_keyframe_insert_keyingset
    ):
        flags = get_keying_flags(context)
        if context.preferences.edit.use_keyframe_insert_available:
            flags.add('INSERTKEY_AVAILABLE')
        if ts.auto_keying_mode == 'REPLACE_KEYS':
            flags.add('INSERTKEY_REPLACE')
        return flags
    else:
        return None


def keyframe_channels(pbone, prop_name):
    prop_value = getattr(pbone, prop_name)
    for i, value in enumerate(prop_value):
        pbone.keyframe_insert(prop_name, index=i, group=pbone.name)


def keyframe_transform_properties(
    obj,
    bone_name,
):
    "Keyframe transformation properties, taking flags and mode into account, and avoiding keying locked channels."
    bone = obj.pose.bones[bone_name]

    # Location.
    if not bone.bone.use_connect:
        keyframe_channels('location', bone.lock_location)

    # Rotation.
    if bone.rotation_mode == 'QUATERNION':
        keyframe_channels('rotation_quaternion')
    elif bone.rotation_mode == 'AXIS_ANGLE':
        keyframe_channels('rotation_axis_angle')
    else:
        keyframe_channels('rotation_euler', bone.lock_rotation)

    # Scale.
    keyframe_channels('scale', bone.lock_scale)


def set_transform_from_matrix(
    context,
    obj,
    bone_name,
    target_matrix,
    *,
    space='POSE',
):
    """Apply the matrix to the transformation of the bone, taking locked channels,
    mode and certain constraints into account, and optionally keyframe it."""
    bone = obj.pose.bones[bone_name]

    # Set the bone transforms in pose space in a way that accounts for additive constraints
    if space != 'POSE':
        target_matrix = obj.convert_space(
            pose_bone=bone, matrix=target_matrix, from_space=space, to_space='POSE'
        )

    pose_matrix_pre_constraints = obj.convert_space(
        pose_bone=bone, matrix=bone.matrix_basis, from_space='LOCAL', to_space='POSE'
    )
    pose_matrix_post_constraints = bone.matrix
    constraint_delta = pose_matrix_post_constraints - pose_matrix_pre_constraints

    bone.matrix = target_matrix - constraint_delta

    AutoKeying.autokey_transformation(context, obj.pose.bones[bone_name])


def get_custom_property_value(rig, bone_name, prop_id):
    prop_bone = rig.pose.bones.get(bone_name)
    assert prop_bone, f"Bone snapping failed: Properties bone {bone_name} not found.)"
    assert (
        prop_id in prop_bone
    ), f"Bone snapping failed: Bone {bone_name} has no property {prop_id}"
    return prop_bone[prop_id]


def set_custom_property_value(obj, bone_name, prop, value, *, keyflags=None):
    "Assign the value of a custom property, and optionally keyframe it."
    bone = obj.pose.bones[bone_name]
    bone[prop] = value
    rna_idprop_ui_prop_update(bone, prop)
    if keyflags is not None:
        bone.keyframe_insert(
            rna_idprop_quote_path(prop), group=bone.name, options=keyflags
        )



#######################################
##### Keyframe Baking Operators #######
#######################################


def get_bones(rig, names):
    """Return a list of pose bones from a string of bone names in json format."""
    return list(filter(None, map(rig.pose.bones.get, json.loads(names))))

