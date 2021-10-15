from typing import List, Tuple

import bpy
from bpy.types import Operator, Object
from bpy.props import BoolProperty, StringProperty
from ..rig_features.object import EnsureVisible

class CLOUDRIG_OT_JumpToBone(Operator):
	"""Change context to make a bone visible and active in the metarig or generated rig."""

	bl_idname = "ui.jump_to_target"
	bl_label = "Jump to Target"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	use_target_rig: BoolProperty(
		name		 = "Jump to Target Rig"
		,description = "Toggle to the generated rig before focusing bone"
		,default	 = False
		)
	target_bone: StringProperty(
		name		 = "Target Bone"
		,description = "Use a specific bone as the beginning of the chain, rather than the active bone"
	)

	def execute(self, context):
		rig = context.object

		if self.use_target_rig:
			rig = rig.data.rigify_target_rig
			bpy.ops.object.cloudrig_metarig_toggle()

		bpy.ops.object.mode_set(mode='POSE')

		bone = rig.data.bones.get(self.target_bone)
		assert bone, f'Bone "{self.target_bone}" not in armature "{rig.name}".'

		bpy.ops.pose.select_all(action='DESELECT')
		bone.hide = False
		bone.select = True
		bone_is_visible = any([bone.layers[i] == rig.data.layers[i]==True for i in range(32)])
		if not bone_is_visible:
			for i, l in enumerate(bone.layers):
				if l:
					rig.data.layers[i] = True
					break

		rig.data.bones.active = bone

		return { 'FINISHED' }

registry = [
	CLOUDRIG_OT_JumpToBone
]
