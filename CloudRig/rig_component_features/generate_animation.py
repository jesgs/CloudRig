# SPDX-License-Identifier: GPL-3.0-or-later

from math import radians as rad

from bpy.types import Action, ActionSlot, FCurve
from bpy_extras import anim_utils

from .bone_info import BoneInfo


class CloudAnimationMixin:
    """Mixin class for rig classes who want to generate actions to test out deformations."""

    def test_action_create_fcurves(
        self, action: Action, slot: ActionSlot, bones: list[BoneInfo], data_path: str
    ) -> dict[str, list[FCurve]]:
        curve_map = {}

        channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        assert channelbag, "Could not find Channelbag while creating Test Animation."

        for bone in bones:
            full_data_path = f'pose.bones["{bone.name}"].{data_path}'
            curves = []
            for i in range(3):
                curve = channelbag.fcurves.new(full_data_path, index=i, group_name=bone.name)
                curves.append(curve)
            curve_map[bone.name] = curves
        return curve_map

    def create_keyframes_on_curves(
        self,
        curve_map: dict[str, list[FCurve]],
        start_frame=1,
        frame_step=15,
        values=[0, 90, 0],
        flip_xyz=[False, False, False],
        is_rotation=True,
        axes=[0, 1, 2],
    ) -> int:
        frame = start_frame
        for bone_name in curve_map.keys():
            curves = curve_map[bone_name]
            for axis_index in axes:
                curve = curves[axis_index]
                curve.color_mode = 'AUTO_RGB'
                curve.keyframe_points.add(len(values))
                for i, value in enumerate(values):
                    kp = curve.keyframe_points[i]
                    if is_rotation:
                        value = rad(value)
                    if flip_xyz[axis_index]:
                        value = -value
                    kp.co = (frame, value)
                    kp.handle_left = (kp.co.x - frame_step / 3, kp.co.y)
                    kp.handle_right = (kp.co.x + frame_step / 3, kp.co.y)
                    kp.handle_left_type = 'AUTO_CLAMPED'
                    kp.handle_right_type = 'AUTO_CLAMPED'
                    frame += frame_step
                frame -= frame_step

        return frame

    def disable_property_until_frame(self, action: Action, slot: ActionSlot, last_frame: int, prop_id: str):
        prop_bone = self.properties_bone

        channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        assert channelbag, "Could not find Channelbag while creating Test Animation."

        data_path = f'pose.bones["{prop_bone.name}"]["{prop_id}"]'
        # Create FCurve for IK/FK toggle
        fc = channelbag.fcurves.find(data_path, index=-1)
        if not fc:
            fc = channelbag.fcurves.new(data_path, index=-1, group_name=prop_bone.name)

        # Add keyframes
        fc.keyframe_points.add(2)
        fc.keyframe_points[0].co = (0, 0)
        fc.keyframe_points[1].co = (last_frame, 1)
        fc.keyframe_points[0].interpolation = 'CONSTANT'
        fc.keyframe_points[1].interpolation = 'CONSTANT'
