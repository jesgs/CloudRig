import bpy
from bpy.props import BoolProperty

from ..rig_features.ui import is_cloud_metarig
from ..rig_features.object import EnsureVisible
from ..generation.cloudrig import register_hotkey

def safe_generate(context, metarig):
	# Generating requires the metarig to be the active object, and the target rig to be visible.

	meta_visible = EnsureVisible(metarig)
	target_rig = metarig.data.rigify_target_rig
	rig_visible = None
	if target_rig:
		rig_visible = EnsureVisible(target_rig)

	# Generate.
	context.view_layer.objects.active = metarig
	if is_cloud_metarig(metarig):
		bpy.ops.pose.cloudrig_generate()
	else:
		bpy.ops.pose.rigify_generate()

	bpy.ops.object.cloudrig_refresh_drivers(selected_only=False)

	meta_visible.restore()
	if rig_visible:
		rig_visible.restore()

def find_metarigs_in_scene(scene):
	metarigs = []
	for o in scene.objects:
		if o.type != 'ARMATURE': continue
		if 'rig_id' in o.data: continue
		for pb in o.pose.bones:
			if pb.rigify_type != "":
				metarigs.append(o)
				break
	return metarigs

class Generate_All_Rigify_Rigs(bpy.types.Operator):
	"""Generate all Rigify rigs in the scene"""
	bl_idname = "object.generate_all_rigify_rigs"
	bl_label = "Generate All"
	bl_options = {'REGISTER', 'UNDO'}

	focus_generated: BoolProperty(
		name = "Focus Generated"
		,default = True
		,description = "After successfully generating a single rig, hide the metarig, unhide the generated rig, enter the same mode as the current mode, and match bone selection states where possible"
	)

	def execute(self, context):
		obj = context.object
		rigs_generated = 0
		rigs_failed = 0

		### Save state so it can be restored for convenience
		state_mode = 'OBJECT'
		state_active_bone = context.active_pose_bone.name if context.active_pose_bone else ""
		state_selected_bones = [bone.name for bone in context.selected_pose_bones] if context.selected_pose_bones else []
		state_hide_bones = {}
		state_layers = []

		### Attempt to generate all rigs, keep track of failures
		for metarig in find_metarigs_in_scene(context.scene):
			if obj in [metarig, metarig.data.rigify_target_rig]:
				state_mode = context.mode
				if obj and metarig.data.rigify_target_rig == obj:
					state_hide_bones = {bone.name : bone.hide for bone in obj.data.bones}
					state_layers = obj.data.layers[:]
			try:
				safe_generate(context, metarig)
				rigs_generated += 1
			except Exception as e:
				rigs_failed += 1
				raise e
		
		self.report_generation(rigs_generated, rigs_failed)

		if self.focus_generated and rigs_generated == 1 and rigs_failed == 0:
			self.restore_state(context, metarig, state_mode, state_active_bone,
						state_selected_bones, state_hide_bones, state_layers)

		return { 'FINISHED' }

	def report_generation(self, successes=0, failures=0):
		"""Report whether metarigs generated successesfully or failed."""
		if successes == 0 and failures == 0:
			self.report({'INFO'}, "No rigs found to generate!")
		elif successes > 0 and failures > 0:
			self.report({'INFO'}, f"{failures} rig{'s' if failures>1 else ''} failed to generate. ({successes} succeeded.)")
		elif failures > 0:
			self.report({'ERROR'}, f"{failures} rig{'s' if failures>1 else ''} failed to generate. See the Rigify Log on the Metarig for more details.")
		else:
			self.report({'INFO'}, f"{successes} rig{'s' if successes>1 else ''} successfully generated!")

	def restore_state(self, context, metarig, mode, active_bone_name="", selected_bone_names="", hide_bones={}, layers=[]):
		"""Restore state for convenience."""
		metarig.hide_set(True)
		rig = metarig.data.rigify_target_rig
		rig.hide_set(False)
		bpy.ops.object.mode_set(mode='OBJECT')
		context.view_layer.objects.active = rig
		rig.select_set(True)

		if mode in ['OBJECT', 'EDIT', 'POSE']:
			bpy.ops.object.mode_set(mode=mode)
	
		rig = context.object
		if active_bone_name in rig.pose.bones:
			rig.data.bones.active = rig.data.bones[active_bone_name]
		
		for bone_name in selected_bone_names:
			if bone_name in rig.data.bones:
				rig.data.bones[bone_name].select = True

		if layers:
			rig.data.layers = layers[:]

		for bone_name in hide_bones.keys():
			bone = rig.data.bones.get(bone_name)
			if not bone: continue
			bone.hide = hide_bones[bone_name]

def register():
	from bpy.utils import register_class
	register_class(Generate_All_Rigify_Rigs)

	register_hotkey(Generate_All_Rigify_Rigs.bl_idname, {'type': "R", 'value': "PRESS", 'ctrl': True, 'alt': True}, key_cat="Object Mode")


def unregister():
	from bpy.utils import unregister_class
	unregister_class(Generate_All_Rigify_Rigs)