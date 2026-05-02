import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Object, Operator, PoseBone
from bpy.utils import flip_name
from mathutils import Vector

from ..bs_utils.hotkeys import register_hotkey
from ..generation.cloudrig import find_cloudrig, is_cloud_metarig
from ..utils.rig import get_pbones_of_selected


class POSE_OT_scale_custom_shape(Operator):
    bl_idname = "pose.scale_custom_shape"
    bl_label = iface_("Scale Custom Shape")
    bl_description = "Scale custom shape of selected pose bones.\n\nShift: More precision\nAlt: Control Bendy Bone display size (only if that display type is already set)\nCtrl: Force Uniform Scale"
    bl_options = {'REGISTER', 'UNDO'}

    sensitivity: bpy.props.FloatProperty(
        name="Sensitivity",
        default=0.01,
        min=0.0001,
    )

    @classmethod
    def poll(cls, context):
        def poll_bone(pbone: PoseBone) -> bool:
            if pbone.id_data.mode == 'POSE' and pbone.custom_shape:
                return True

            if is_cloud_metarig(pbone.id_data) and pbone.cloudrig_component.component_pbone:
                return not bool(pbone.custom_shape)

            return False

        bones = [
            pb for pb in get_pbones_of_selected(context, whole_ebone=True)
            if poll_bone(pb)
        ]
        if not bones:
            cls.poll_message_set("No pose bones with custom shapes selected")
            return False
        return True

    @staticmethod
    def get_rig(context) -> Object:
        return find_cloudrig(context) or context.pose_object or context.active_object

    def invoke(self, context, event):
        self.rig = rig = self.get_rig(context)
        self.pbones = [
            pb for pb in get_pbones_of_selected(context, whole_ebone=True)
            if (pb.custom_shape or is_cloud_metarig(rig))
        ]

        self.mirror_pbones = []
        if rig.data.use_mirror_x:
            for pb in self.pbones[:]:
                opp_pb = rig.pose.bones.get(flip_name(pb.name))
                if opp_pb and opp_pb not in self.pbones:
                    self.mirror_pbones.append(opp_pb)
            self.pbones += self.mirror_pbones

        if not self.pbones:
            self.report({'WARNING'}, "No pose bones with custom shapes selected")
            return {'CANCELLED'}

        # Cache initial state
        self.initial_states = {
            pb: (pb.custom_shape_scale_xyz.copy(), pb.bone.bbone_x, pb.bone.bbone_z)
            for pb in self.pbones
        }

        self.prev_mouse_x = event.mouse_x
        self.constraint_axis = None  # None, 0, 1, 2

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self._restore()
            return {'CANCELLED'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            return {'FINISHED'}

        if event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS':
            axis = {'X': 0, 'Y': 1, 'Z': 2}[event.type]
            self.constraint_axis = None if self.constraint_axis == axis else axis
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            delta = (event.mouse_x - self.prev_mouse_x) * self.sensitivity
            if event.shift:
                delta *= 0.1
            scale_factor = 1.0 + delta

            for pb in self.pbones:
                if pb in self.mirror_pbones:
                    continue

                if self.constraint_axis is None:
                    if event.alt:
                        pb.bone.bbone_x *= scale_factor
                        pb.bone.bbone_z *= scale_factor
                    else:
                        pb.custom_shape_scale_xyz *= scale_factor
                else:
                    if event.alt and (pb.bone.display_type == 'BBONE' or (pb.id_data.data.display_type == 'BBONE' and pb.bone.display_type=='ARMATURE_DEFINED')):
                        if self.constraint_axis == 0:
                            pb.bone.bbone_x *= scale_factor
                        if self.constraint_axis == 2:
                            pb.bone.bbone_z *= scale_factor
                    else:
                        pb.custom_shape_scale_xyz[self.constraint_axis] *= scale_factor

                if event.ctrl:
                    self.constraint_axis = None
                    if event.alt:
                        avg = (pb.bone.bbone_x + pb.bone.bbone_z)/2
                        pb.bone.bbone_x = pb.bone.bbone_z = avg
                    else:
                        avg = sum((abs(s) for s in pb.custom_shape_scale_xyz))/3
                        pb.custom_shape_scale_xyz = (avg, avg, avg)

                if self.rig.data.use_mirror_x:
                    opp_pb = self.rig.pose.bones.get(flip_name(pb.name))
                    if opp_pb and opp_pb != pb:
                        opp_pb.bone.bbone_x = pb.bone.bbone_x
                        opp_pb.bone.bbone_z = pb.bone.bbone_z
                        opp_pb.custom_shape_scale_xyz = pb.custom_shape_scale_xyz * Vector((-1, 1, 1))


            self.prev_mouse_x = event.mouse_x

            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def _restore(self):
        for pb, (scale, bbone_x, bbone_z) in self.initial_states.items():
            pb.custom_shape_scale_xyz = scale
            pb.bone.bbone_x = bbone_x
            pb.bone.bbone_z = bbone_z


def draw_scale_custom_shape_op(self, context):
    self.layout.operator(POSE_OT_scale_custom_shape.bl_idname)


registry = [POSE_OT_scale_custom_shape]


def register():
    bpy.types.VIEW3D_MT_transform_armature.append(draw_scale_custom_shape_op)
    for keymap_name in ('Pose', 'Armature'):
        register_hotkey(
            POSE_OT_scale_custom_shape.bl_idname,
            hotkey_kwargs={'type': "S", 'value': "PRESS", 'alt' : True, 'shift': True},
            keymap_name=keymap_name,
        )

def unregister():
    bpy.types.VIEW3D_MT_transform_armature.remove(draw_scale_custom_shape_op)
