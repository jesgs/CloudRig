from bpy.types import Operator, Bone, EditBone, PoseBone
from bpy.props import IntProperty, StringProperty, BoolProperty
from ..generation import naming

def deselect_all_bones(context):
	if context.mode == 'EDIT_ARMATURE':
		bones = context.selected_editable_bones
	else:
		bones = [pb.bone for pb in context.selected_pose_bones]
	for b in bones:
		b.select = False
		if context.mode == 'EDIT_ARMATURE':
			b.select_head = False
			b.select_tail = False

def ensure_visible_bone_layer(bone: Bone or EditBone or PoseBone):
	"""If target bone not in any enabled layers, enable first one."""
	if type(bone) == PoseBone:
		armature = bone.id_data.data
		bone = bone.bone
	else:
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

def increment_bone_name(bone_name: str, increment: int):
	# Increment LAST number in the name.
	# TODO: Use RegEx to support more than a single digit here.
	for i, c in enumerate(list(reversed(bone_name))):
		if c.isdecimal():
			num = int(c)
			return bone_name.replace(c, str(num+increment))
	return bone_name

def get_selected_bones(context):
	"""Return a list of Bones or EditBones depending on context."""
	if context.mode == 'EDIT_ARMATURE':
		return context.selected_editable_bones[:]
	else:
		return [pb.bone for pb in context.selected_pose_bones]

def is_active_bone(context, bone: Bone or EditBone or PoseBone):
	"""Return whether the passed bone is the active one"""
	if type(bone) == PoseBone:
		armature = bone.id_data.data
		bone = bone.bone
	else:
		armature = bone.id_data

	if context.mode == 'EDIT_ARMATURE' and bone.name == armature.edit_bones.active.name:
		return True
	elif context.active_pose_bone.bone == bone:
		return True
	return False

def set_active_bone(context, bone: Bone or EditBone or PoseBone):
	"""Set the active bone, regardless of if we're in edit mode or not.
	Also account for active vertex group when in weight paint mode.
	"""

	if not bone:
		return
	if type(bone) == PoseBone:
		armature = bone.id_data.data
		bone = bone.bone
	else:
		armature = bone.id_data

	if context.mode == 'EDIT_ARMATURE':
		armature.edit_bones.active = bone
	else:
		armature.bones.active = bone

	if context.mode == 'PAINT_WEIGHT':
		if bone.name in context.object.vertex_groups:
			context.object.vertex_groups.active = context.object.vertex_groups[bone.name]

def reveal_and_select(context, bone: Bone or EditBone or PoseBone):
	if type(bone) == PoseBone:
		bone = bone.bone
	bone.hide = False
	bone.select = True
	if context.mode == 'EDIT_ARMATURE':
		bone.select_head = True
		bone.select_tail = True

class BoneSelectOperatorMixin:
	extend_selection: BoolProperty(
		name="Extend Selection", 
		description="Bones that are already selected will remain selected"
	)

	@classmethod
	def poll(cls, context):
		return context.active_bone or context.active_pose_bone

	def execute(self, context):
		if not self.extend_selection:
			deselect_all_bones(context)
		
		return {'FINISHED'}


class POSE_OT_select_bone_by_name(Operator, BoneSelectOperatorMixin):
	"""Select the bone of a given name. Intended for use in pie menus"""
	bl_idname = "pose.select_bone_by_name"
	bl_label = "Select Bone By Name"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	bone_name: StringProperty(
		name="Bone Name",
		description = "Name of the bone to select"
	)

	@classmethod
	def poll(cls, context):
		return context.pose_object or (context.object and context.object.type=='ARMATURE')

	def execute(self, context):
		rig = context.pose_object or context.object
		if rig.mode == 'EDIT':
			bone = rig.data.edit_bones.get(self.bone_name)
		else:
			bone = rig.data.bones.get(self.bone_name)
		
		if not bone:
			self.report({'ERROR'}, "Bone name not found in rig: " + self.bone_name)
			return {'CANCELLED'}

		super().execute(context)

		ensure_visible_bone_layer(bone)
		reveal_and_select(context, bone)
		set_active_bone(context, bone)

		return {'FINISHED'}


class POSE_OT_select_bone_by_name_relation(Operator, BoneSelectOperatorMixin):
	"""Select a bone with a name relation. Intended to be used with user-defined shortcuts"""
	bl_idname = "pose.select_bone_by_name_relation"
	bl_label = "Select Bone By Name Relation"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	strip_start: IntProperty(
		name="Strip Start", 
		description="Strip this many characters from the start of the bone name. If this is used, the prefix/suffix separator functionality is not used",
		default=0
	)
	strip_end: IntProperty(
		name="Strip End", 
		description="Strip this many characters from the end of the bone name. If this is used, the prefix/suffix separator functionality is not used",
		default=0
	)

	prefix_separator: StringProperty(
		name="Prefix Separator", 
		description="String to use as delimiter for splitting the active bone's name into its prefix and rest halves",
		default="-"
	)
	prefix: StringProperty(
		name="Prefix", 
		description="Add these characters to the start of the bone name",
		default=""
	)

	suffix_separator: StringProperty(
		name="Suffix Separator", 
		description="String to use as delimiter for splitting the active bone's name into its suffix and rest halves",
		default = "."
	)
	suffix: StringProperty(
		name="Suffix", 
		description="Add these characters to the end of the bone name",
		default=""
	)

	increment: IntProperty(
		name="Increment", 
		description="Increment the last number in the bone name by this amount. Can be negative", 
		min=-1, max=1, default=0
	)

	def execute(self, context):
		rig = context.pose_object or context.object
		active_target_bone = None

		selected_bones = get_selected_bones(context)

		super().execute(context)

		for bone in selected_bones:
			bone_name = bone.name
			bone_name = bone_name[self.strip_start:]
			if self.strip_end > 0:
				bone_name = bone_name[:-self.strip_end]

			if bone_name != bone.name:
				bone_name = self.prefix + bone_name + self.suffix
			else:
				if self.prefix:
					sliced = naming.slice_name(bone_name)
					bone_name = naming.make_name([self.prefix], sliced[1], sliced[2])
				if self.suffix:
					sliced = naming.slice_name(bone_name)
					bone_name = naming.make_name(sliced[0], sliced[1], [self.suffix])

			bone_name = increment_bone_name(bone_name, self.increment)

			if context.mode == 'EDIT_ARMATURE':
				target_bone = rig.data.edit_bones.get(bone_name)
			else:
				target_bone = rig.data.bones.get(bone_name)
			if not target_bone:
				self.report({'INFO'}, f'Bone "{bone_name}" not found.')
				continue

			reveal_and_select(context, target_bone)
			if is_active_bone(context, bone):
				active_target_bone = target_bone

			if target_bone.hide:
				self.report({'WARNING'}, f'Bone "{bone_name}" could not be made visible.')
				continue

			ensure_visible_bone_layer(target_bone)

		set_active_bone(context, active_target_bone)

		return {'FINISHED'}


class POSE_OT_select_parent_bone(Operator, BoneSelectOperatorMixin):
	"""Select parent of the current bone"""
	bl_idname = "pose.select_parent_bone"
	bl_label = "Select Parent Bone"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		bone = context.active_bone or context.active_pose_bone
		return bone and bone.parent

	def execute(self, context):
		super().execute(context)

		active_bone = context.active_bone or context.active_pose_bone

		ensure_visible_bone_layer(active_bone.parent)
		set_active_bone(context, active_bone.parent)

		return {'FINISHED'}


registry = [
	POSE_OT_select_bone_by_name,
	POSE_OT_select_bone_by_name_relation,
	POSE_OT_select_parent_bone
]
