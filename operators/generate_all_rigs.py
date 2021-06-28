import bpy
from bpy.props import BoolProperty

from ..utils.ui import is_cloud_metarig
from ..utils.object import EnsureVisible

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
	"""Generate all Rigify rigs in the scene."""
	bl_idname = "object.generate_all_rigify_rigs"
	bl_label = "Generate All Rigify Rigs"
	bl_options = {'REGISTER', 'UNDO'}

	auto_hide: BoolProperty(
		name="Auto Hide/Unhide"
		,default=False
		,description="Enable additional convenience functionality when generating a single rig: After a successful generation, hide the metarig, unhide the generated rig, and enter the same mode on the generated rig as the current mode"
	)
	# TODO: Options to preserve pose and selected/active bones would be a nice bonus both here and in toggle_metarig.

	def execute(self, context):
		rigs_generated = 0
		rigs_failed = 0
		auto_mode = 'OBJECT'
		for metarig in find_metarigs_in_scene(context.scene):
			if metarig == context.object:
				auto_mode = metarig.mode
			try:
				safe_generate(context, metarig)
				rigs_generated += 1
			except Exception as e:
				rigs_failed += 1
				raise e
		if rigs_generated == 0 and rigs_failed == 0:
			self.report({'INFO'}, "No rigs found to generate!")
		elif rigs_generated > 0 and rigs_failed > 0:
			self.report({'INFO'}, f"{rigs_failed} rig{'s' if rigs_failed>1 else ''} failed to generate. ({rigs_generated} succeeded.)")
		elif rigs_failed > 0:
			self.report({'ERROR'}, f"{rigs_failed} rig{'s' if rigs_failed>1 else ''} failed to generate. See the Rigify Log on the Metarig for more details.")
		else:
			self.report({'INFO'}, f"{rigs_generated} rig{'s' if rigs_generated>1 else ''} successfully generated!")

		if self.auto_hide and rigs_generated == 1 and rigs_failed == 0:
			metarig.hide_set(True)
			rig = metarig.data.rigify_target_rig
			rig.hide_set(False)
			bpy.ops.object.mode_set(mode='OBJECT')
			context.view_layer.objects.active = rig
			rig.select_set(True)
			bpy.ops.object.mode_set(mode=auto_mode)

		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(Generate_All_Rigify_Rigs)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(Generate_All_Rigify_Rigs)