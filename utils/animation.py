# Typing
import bpy
from typing import List, Dict
from ..bone import BoneInfo

from math import radians as rad

class CloudAnimationMixin:
	"""Mixin class for functions to generate actions with animation."""

	def initialize_test_action(self):
		self.test_action = self.generator.params.cloudrig_parameters.test_action
		if self.rigify_parent:
			self.first_test_frame = self.rigify_parent.last_test_frame
			self.last_test_frame = self.rigify_parent.last_test_frame
		else:
			self.first_test_frame = 1
			self.last_test_frame = 1

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

	def test_action_create_keyframes(self
			,curve_map: Dict[str, List[bpy.types.FCurve]]
			,start_frame = 1
			,frame_step = 15
			,angles = [0, 90, 0]
			,axes = [0, 1, 2]
		) -> int:
		frame = start_frame
		for bone_name in curve_map.keys():
			curves = curve_map[bone_name]
			for axis_index in axes:
				curve = curves[axis_index]
				curve.color_mode = 'AUTO_RGB'
				curve.keyframe_points.add(len(angles))
				for i, angle in enumerate(angles):
					kp = curve.keyframe_points[i]
					kp.co = (frame, rad(angle))
					kp.handle_left = (kp.co.x - frame_step/3, kp.co.y)
					kp.handle_right = (kp.co.x + frame_step/3, kp.co.y)
					kp.handle_left_type = 'AUTO_CLAMPED'
					kp.handle_right_type = 'AUTO_CLAMPED'
					frame += frame_step
				frame -= frame_step
		
		return frame