import bpy
from bpy.props import BoolProperty
from ..utils.naming import slice_name

# An operator to toggle between the metarig and the generated rig.
# The generated rig does not store a reference to the metarig, so just bruteforce search it.

# This operator should only hide/unhide the objects with the eye icon.
# If the objects are not visible when the eye icon is disabled, the operator should fail gracefully.

# Also in the case of either switch, match the armature layers.

PREFIX_PRIORITY = ['FK', 'IK', 'DEF', 'STR', 'ORG']

class CLOUDRIG_OT_MetarigToggle(bpy.types.Operator):
	"""Switch the active object between the generated rig and the metarig"""

	bl_idname = "object.cloudrig_toggle_metarig"
	bl_label = "Toggle Metarig/Generated rig"
	bl_options = {'REGISTER', 'UNDO'}

	match_layers: BoolProperty(name="Match Layers", default=True, description="Keep the active layer list between armatures when switching between them, as if they shared active layers")
	match_selection: BoolProperty(name="Match Selection", default=True, description="Try to match bone selection when switching between armatures. Also works with non-exact matches")

	@classmethod
	def poll(cls, context):
		return context.object and context.object.type == 'ARMATURE' and context.object.visible_get()

	def switch_rig_focus(self, context, from_arm, to_arm, match_layers=True, match_selection=True):
		org_mode = from_arm.mode
		bpy.ops.object.mode_set(mode='OBJECT')
		from_arm.hide_set(True)

		to_arm.hide_set(False)
		if not to_arm.visible_get():
			self.report({'ERROR'}, f'Could not make "{to_arm.name}" visible. Make sure it is enabled, and in an enabled collection!')
			return {'CANCELLED'}
		context.view_layer.objects.active = to_arm
		to_arm.select_set(True)
		bpy.ops.object.mode_set(mode=org_mode)


		if match_layers:
			to_arm.data.layers = from_arm.data.layers[:]
		if match_selection:
			for b in to_arm.data.bones:
				b.select = False

			active = from_arm.data.bones.active
			if active:
				to_active = to_arm.data.bones.get(active.name)
				if to_active:
					to_arm.data.bones.active = to_active

			# TODO: For behaviour that would be both smarter and better, 
			# we should store the bone name mapping on the metarig 
			# (which meta bone generated which bones).
			selected_names = [b.name for b in from_arm.data.bones if b.select]
			for bonename in selected_names:
				if bonename in to_arm.data.bones:
					to_arm.data.bones[bonename].select = True
				else:
					bone_visible = lambda arm, b: not b.hide and any([b.layers[i] == arm.layers[i]==True for i in range(32)])
					name_match = lambda a, b: a in b or b in a
					matches = [b.name for b in to_arm.data.bones if bone_visible(to_arm.data, b) and name_match(b.name, bonename)]
					if len(matches) == 1:
						to_arm.data.bones[matches[0]].select = True
					else:
						found = False
						for prefix in PREFIX_PRIORITY:
							if found:
								break
							for match in matches:
								prefixes = slice_name(match)[0]
								if prefix in prefixes:
									to_arm.data.bones[match].select = True
									found = True
									break

		return {'FINISHED'}

	def execute(self, context):
		ob = context.object

		if ob.data.rigify_target_rig:
			# If the active object is a metarig, switch to the generated rig.
			metarig = ob
			rig = metarig.data.rigify_target_rig
			return self.switch_rig_focus(context, metarig, rig, self.match_layers, self.match_selection)

		# Otherwise, try to find a metarig that references this rig
		for metarig in bpy.data.objects:
			if metarig.type != 'ARMATURE': continue
			if metarig.data.rigify_target_rig == ob:
				break
			metarig = None
		if not metarig:
			self.report({'ERROR'}, "No metarig found for this rig.")
			return {'CANCELLED'}

		# Switch from the rig to the metarig
		return self.switch_rig_focus(context, ob, metarig, self.match_layers, self.match_selection)

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_MetarigToggle)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_MetarigToggle)