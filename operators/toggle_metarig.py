from bpy.types import Armature, Bone, Object, Operator

import bpy
from bpy.props import BoolProperty
from ..generation.naming import slice_name
from ..generation.cloudrig import register_hotkey

# An operator to toggle between the metarig and the generated rig.
# The generated rig does not store a reference to the metarig, so just bruteforce search it.

# This operator should only hide/unhide the objects with the eye icon.
# If the objects are not visible when the eye icon is disabled, the operator should fail gracefully.

# Also in the case of either switch, match the armature layers.

PREFIX_PRIORITY = ['FK', 'IK', 'DEF', 'STR', 'ORG']

class CLOUDRIG_OT_MetarigToggle(Operator):
	"""Switch the active object between the generated rig and the metarig"""

	bl_idname = "object.cloudrig_metarig_toggle"
	bl_label = "Toggle Meta/Generated Rig"
	bl_options = {'REGISTER', 'UNDO'}

	match_layers: BoolProperty(
		name		 = "Match Layers"
		,default	 = True
		,description = "Keep the active layer list between armatures when switching between them, as if they shared active layers"
	)
	match_selection: BoolProperty(
		name		 = "Match Selection"
		,default	 = True
		,description = "Try to match bone selection when switching between armatures. Also works with non-exact matches"
	)

	@classmethod
	def poll(cls, context):
		rig = context.active_object
		return rig and rig.type == 'ARMATURE' and rig.visible_get()

	def execute(self, context):
		rig = context.active_object
		metarig = None

		if rig.data.rigify_target_rig:
			# If the active object is a metarig, switch to the generated rig.
			metarig = rig
			rig = metarig.data.rigify_target_rig
			self.switch_rig_focus(context, metarig, rig, self.match_layers, self.match_selection)
			return {'FINISHED'}

		# Otherwise, try to find a metarig that references this rig
		metarig = self.find_metarig_of_rig(context, rig)
		if not metarig:
			self.report({'ERROR'}, "No metarig found for this rig.")
			return {'CANCELLED'}

		# Switch from the rig to the metarig
		self.switch_rig_focus(context, rig, metarig, self.match_layers, self.match_selection)
		return {'FINISHED'}

	def find_metarig_of_rig(self, context, rig: Object):
		if rig.name.startswith('FAILED-RIG-'):
			metarig = context.scene.objects.get(rig.name.replace('FAILED-RIG-', ""))
			if not metarig:
				metarig = context.scene.objects.get(rig.name.replace('FAILED-RIG-', "META-"))
			return metarig

		for o in context.scene.objects:
			if o.type != 'ARMATURE': continue
			if o.data.rigify_target_rig == rig:
				return o

	def switch_rig_focus(self, context,
			from_arm: Object,
			to_arm: Object,
			match_layers = True,
			match_selection = True
		):
		org_mode = from_arm.mode

		to_arm.hide_set(False)
		if not to_arm.visible_get():
			self.report({'ERROR'}, f'Could not make "{to_arm.name}" visible. Make sure it is enabled, and in an enabled collection!')
			return {'CANCELLED'}

		bpy.ops.object.mode_set(mode='OBJECT')
		from_arm.hide_set(True)

		context.view_layer.objects.active = to_arm
		to_arm.select_set(True)
		bpy.ops.object.mode_set(mode=org_mode)

		if match_layers:
			to_arm.data.layers = from_arm.data.layers[:]

		# When switching between the metarig and the generated rig,
		# match the bone selection as much as possible, unless a lot of bones are selected.
		selected = [b for b in from_arm.data.bones if b.select]
		if match_selection and org_mode in ['EDIT', 'POSE'] and len(selected) < 10:
			self.match_bone_selection(from_arm, to_arm)

	def match_bone_selection(self,
			from_arm: Object,
			to_arm: Object
		):
		self.deselect_all_bones(to_arm)
		self.match_active_bone(from_arm, to_arm)

		# Match selected bones, without affecting bone visibilities, and using a prefix priority system.
		# This means that for each selected bone in the source armature,
		# only one or zero bones are selected in the target armature.
		# Zero if no visible matches are found.

		# If an exact match is found, use that. This is rare, since most bones get prefixes during generation (FK-, DEF-, etc).

		# If multiple matches are found, one is chosen based on its prefix
		# (higher priority prefix wins).
		selected_names = [b.name for b in from_arm.data.bones if b.select]
		for bone_name in selected_names:
			bone = self.get_visible_bone_with_similar_name(to_arm.data, bone_name)
			if bone:
				bone.select = True

	def deselect_all_bones(self, armature: Armature):
		for b in armature.data.bones:
			b.select = False

	def match_active_bone(self, from_arm: Object, to_arm: Object):
		"""If there is an exact match for the active bone, make the matching bone active."""
		active = from_arm.data.bones.active
		if active:
			to_active = to_arm.data.bones.get(active.name)
			if to_active:
				to_arm.data.bones.active = to_active

	def get_visible_bone_with_similar_name(self,
			armature: Armature,
			bone_name: str
		) -> Bone:
		bone_is_visible = lambda b: not b.hide and any([b.layers[i] == armature.layers[i]==True for i in range(32)])
		names_match = lambda a, b: a in b or b in a

		if bone_name in armature.bones and bone_is_visible(armature.bones[bone_name]):
			# If we have an exact match and it's visible, return it.
			# (Just for optimization)
			return armature.bones[bone_name]

		matches = [
			b.name for b in armature.bones
			if bone_is_visible(b) and names_match(b.name, bone_name)
		]
		if len(matches) == 1:
			# If there is only one match and it's visible return it.
			return armature.bones[matches[0]]
		else:
			for prefix in PREFIX_PRIORITY:
				for match in matches:
					prefixes = slice_name(match)[0]
					if prefix in prefixes:
						return armature.bones[match]

registry = [
	CLOUDRIG_OT_MetarigToggle
]

def register():
	register_hotkey(CLOUDRIG_OT_MetarigToggle.bl_idname
		,hotkey_kwargs = {'type': "T", 'value': "PRESS", 'shift': True}
		,key_cat = "3D View"
		,space_type = "VIEW_3D"
	)
