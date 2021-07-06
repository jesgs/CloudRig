import bpy
from bpy.props import BoolProperty

# An operator to toggle between the metarig and the generated rig.
# The generated rig does not store a reference to the metarig, so just bruteforce search it.

# This operator should only hide/unhide the objects with the eye icon.
# If the objects are not visible when the eye icon is disabled, the operator should fail gracefully.

# Also in the case of either switch, match the armature layers.

class CLOUDRIG_OT_MetarigToggle(bpy.types.Operator):
	"""Switch the active object between the generated rig and the metarig"""

	bl_idname = "object.cloudrig_toggle_metarig"
	bl_label = "Toggle Metarig/Generated rig"
	bl_options = {'REGISTER', 'UNDO'}

	# TODO: This is implemented, just needs to be hidden behind an if statement.
	match_layers: BoolProperty(name="Match Layers", default=True, description="Keep the active layer list between armatures when switching between them, as if they shared active layers")
	# TODO: Implement this. Check if the majority of bones are hidden or un-hidden when switching. Set the majority as the default, then cherrypick bones that should be non-default based on name matching.
	# match_hide: BoolProperty(name="Match Hiding", default=True, description="Try to match bone visibilities when switching between armatures, as if they shared bones")
	# TODO: Implement this. For selected bones, find all visible matches in the other rig, and select the bone if there is only one match or if there is an exact match.
	# match_selection: BoolProperty(name="Match Selection", default=True, description="Try to match bone selection when switching between armatures, as if they shared bones. Will also work with non-exact matches, as long as only one close match is found")

	@classmethod
	def poll(cls, context):
		return context.object and context.object.type == 'ARMATURE' and context.object.visible_get()

	def execute(self, context):
		ob = context.object
		org_mode = ob.mode

		# If the active object is a metarig
		if ob.data.rigify_target_rig:
			rig = ob.data.rigify_target_rig
			rig.hide_set(False)
			if not rig.visible_get():
				self.report({'ERROR'}, "Could not make the rig visible. Make sure it's enabled, and in an enabled collection!")
				return {'CANCELLED'}
			bpy.ops.object.mode_set(mode='OBJECT')
			ob.hide_set(True)
			context.view_layer.objects.active = rig
			rig.select_set(True)
			bpy.ops.object.mode_set(mode=org_mode)

			rig.data.layers = ob.data.layers[:]
		else:
			# Find a metarig that references this rig
			worked = False
			for metarig in bpy.data.objects:
				if metarig.type!='ARMATURE': continue
				if metarig.data.rigify_target_rig != ob: continue

				metarig.hide_set(False)
				if not metarig.visible_get():
					self.report({'ERROR'}, "Could not make the metarig visible. Make sure it's enabled, and in an enabled collection!")
					return {'CANCELLED'}

				bpy.ops.object.mode_set(mode='OBJECT')
				ob.hide_set(True)
				context.view_layer.objects.active = metarig
				metarig.select_set(True)
				bpy.ops.object.mode_set(mode=org_mode)

				metarig.data.layers = ob.data.layers[:]

				worked = True

				break

			if not worked:
				self.report({'WARNING'}, "Could not find a metarig that references this rig, so the operator did nothing.")
				return {'CANCELLED'}

		return {'FINISHED'}



		objs = context.selected_objects if self.selected_only else bpy.data.objects

		for o in objs:
			refresh_drivers(o)
			if hasattr(o, "data") and o.data:
				refresh_drivers(o.data)
			if o.type=='MESH':
				refresh_drivers(o.data.shape_keys)

			for ms in o.material_slots:
				if ms.material:
					refresh_drivers(ms.material)
					refresh_drivers(ms.material.node_tree)

		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_MetarigToggle)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_MetarigToggle)