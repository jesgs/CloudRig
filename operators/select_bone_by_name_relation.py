from bpy.types import Operator, Bone, EditBone
from bpy.props import IntProperty, StringProperty, BoolProperty

class POSE_OT_select_bone_by_name_relation(Operator):
	"""Select a bone with a name relation. Intended to be used with user-defined shortcuts"""
	bl_idname = "pose.select_bone_by_name"
	bl_label = "Select Bone By Name Relation"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	strip_start: IntProperty(name="Strip Start", description="Strip this many characters from the start of the bone name")
	strip_end: IntProperty(name="Strip End", description="Strip this many characters from the end of the bone name")
	prefix: StringProperty(name="Prefix", description="Add these characters to the start of the bone name")
	suffix: StringProperty(name="Suffix", description="Add these characters to the end of the bone name")
	increment: IntProperty(name="Increment", description="Increment the last number in the bone name by this amount. Can be negative", min=-1, max=1, default=0)

	extend_selection: BoolProperty(name="Extend Selection", description="Bones that are already selected will remain selected")

	@classmethod
	def poll(cls, context):
		return context.active_bone or context.active_pose_bone

	@staticmethod
	def deselect_all_bones(context):
		if context.mode == 'EDIT_ARMATURE':
			bones = context.selected_editable_bones
		else:
			bones = [pb.bone for pb in context.selected_pose_bones]
		for b in bones:
			b.select = False

	@staticmethod
	def ensure_visible_bone_layer(bone: Bone or EditBone):
		"""If target bone not in any enabled layers, enable first one."""
		armature = bone.id_data
		any_layer = False
		for i, enabled in enumerate(armature.layers):
			if enabled and bone.layers[i]:
				any_layer = True
				return
		
		if not any_layer:
			for i in range(len(bone.layers)):
				if bone.layers[i]:
					armature.layers[i] = True
					return

	@staticmethod
	def increment_bone_name(bone_name: str, increment: int):
		# Increment LAST number in the name.
		# TODO: Use RegEx to support more than a single digit here.
		for i, c in enumerate(list(reversed(bone_name))):
			if c.isdecimal():
				num = int(c)
				return bone_name.replace(c, str(num+increment))
		return bone_name

	@staticmethod
	def get_selected_bones(context):
		"""Return a list of Bones or EditBones depending on context."""
		if context.mode == 'ARMATURE_EDIT':
			return context.selected_editable_bones[:]
		else:
			return [pb.bone for pb in context.selected_pose_bones]

	@staticmethod
	def is_active_bone(context, bone: Bone or EditBone):
		"""Return whether the passed bone is the active one"""
		rig = bone.id_data
		if context.editable_bones and bone == rig.data.edit_bones.active:
			return True
		elif context.active_pose_bone.bone == bone:
			return True
		return False

	@staticmethod
	def set_active_bone(context, bone: Bone or EditBone):
		"""Set the active bone, regardless of if we're in edit mode or not.
		Also account for active vertex group when in weight paint mode.
		"""

		if not bone:
			return
		armature = bone.id_data
		if context.editable_bones:
			armature.edit_bones.active = bone
		else:
			armature.bones.active = bone

		if context.mode == 'PAINT_WEIGHT':
			if bone.name in context.object.vertex_groups:
				context.object.vertex_groups.active = context.object.vertex_groups[bone.name]

	def execute(self, context):
		rig = context.pose_object or context.object
		active_target_bone = None

		selected_bones = self.get_selected_bones(context)

		if not self.extend_selection:
			self.deselect_all_bones(context)

		for bone in selected_bones:
			bone_name = bone.name
			bone_name = bone_name[self.strip_start:]
			if self.strip_end > 0:
				bone_name = bone_name[:-self.strip_end]
			bone_name = self.prefix + bone_name + self.suffix

			bone_name = self.increment_bone_name(bone_name, self.increment)

			if context.mode == 'EDIT_ARMATURE':
				target_bone = rig.data.edit_bones.get(bone_name)
			else:
				target_bone = rig.data.bones.get(bone_name)
			if not target_bone:
				self.report({'INFO'}, f'Bone "{bone_name}" not found.')
				continue

			target_bone.hide = False
			target_bone.select = True
			if self.is_active_bone(context, bone):
				active_target_bone = target_bone

			if target_bone.hide:
				self.report({'WARNING'}, f'Bone "{bone_name}" could not be made visible.')
				continue

			self.ensure_visible_bone_layer(target_bone)

		self.set_active_bone(context, active_target_bone)

		return {'FINISHED'}

registry = [
	POSE_OT_select_bone_by_name_relation
]
