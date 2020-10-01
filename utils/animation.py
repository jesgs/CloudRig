# Typing
import bpy
from typing import List, Dict
from ..bone import BoneInfo

from math import radians as rad

class CloudAnimationMixin:
	"""Mixin class for functions to generate actions with animation."""

	def test_action_create_fcurves(self
		,action: bpy.types.Action
		,bones: List[BoneInfo]
		,data_path: str
		) -> Dict[str, List[bpy.types.FCurve]]:
		curve_map = {}
		for b in bones:
			full_data_path = f'pose.bones["{b.name}"].{data_path}'
			curves = []
			for i in range(3):
				curve = action.fcurves.new(full_data_path, index=i, action_group=b.name)
				curves.append(curve)
			curve_map[b.name] = curves
		return curve_map

	def create_keyframes_on_curves(self
			,curve_map: Dict[str, List[bpy.types.FCurve]]
			,start_frame = 1
			,frame_step = 15
			,values = [0, 90, 0]
			,flip_xyz = [False, False, False]
			,is_rotation = True
			,axes = [0, 1, 2]
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
					kp.handle_left = (kp.co.x - frame_step/3, kp.co.y)
					kp.handle_right = (kp.co.x + frame_step/3, kp.co.y)
					kp.handle_left_type = 'AUTO_CLAMPED'
					kp.handle_right_type = 'AUTO_CLAMPED'
					frame += frame_step
				frame -= frame_step

		return frame
	
	def disable_property_until_frame(self, action, last_frame, prop_id):
		prop_bone = self.properties_bone

		data_path = f'pose.bones["{prop_bone.name}"]["{prop_id}"]'
		# Create FCurve for IK/FK toggle
		fc = action.fcurves.new(data_path, index=-1, action_group=prop_bone.name)

		# Add keyframes
		fc.keyframe_points.add(2)
		fc.keyframe_points[0].co = (0, 0)
		fc.keyframe_points[1].co = (last_frame, 1)
		fc.keyframe_points[0].interpolation = 'CONSTANT'
		fc.keyframe_points[1].interpolation = 'CONSTANT'