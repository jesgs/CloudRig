import bpy

from ..utils.ui import is_cloud_metarig
from ..utils.object import EnsureVisible

def safe_generate(context, metarig, target_rig):
	# Generating requires the metarig to be the active object, and the target rig to be visible.

	meta_visible = EnsureVisible(metarig)
	rig_visible = EnsureVisible(target_rig)

	# Generate.
	context.view_layer.objects.active = metarig
	if is_cloud_metarig(metarig):
		bpy.ops.pose.cloudrig_generate()
	else:
		bpy.ops.pose.rigify_generate()
		bpy.ops.object.cloudrig_refresh_drivers(selected_only=False)

	meta_visible.restore()
	rig_visible.restore()

class Regenerate_Rigify_Rigs(bpy.types.Operator):
	""" Regenerate all Rigify rigs in the file. (Only works on metarigs that have an existing target rig.) """
	bl_idname = "object.regenerate_all_rigify_rigs"
	bl_label = "Regenerate All Rigify Rigs"
	bl_options = {'REGISTER', 'UNDO'}

	def execute(self, context):
		rigs_generated = 0
		rigs_failed = 0
		for o in bpy.data.objects:
			if o.type!='ARMATURE': continue
			if o.data.rigify_target_rig:
				metarig = o
				target_rig = o.data.rigify_target_rig
				if target_rig:
					try:
						safe_generate(context, metarig, target_rig)
						rigs_generated+=1
					except:
						rigs_failed += 1
		if rigs_generated==0 and rigs_failed==0:
			self.report({'INFO'}, "No rigs found to re-generate!")
		elif rigs_generated>0 and rigs_failed >0:
			self.report({'INFO'}, f"{rigs_failed} rig{'s' if rigs_failed>1 else ''} failed to generate. ({rigs_generated} succeeded.)")
		elif rigs_failed>0:
			self.report({'ERROR'}, f"{rigs_failed} rig{'s' if rigs_failed>1 else ''} failed to generate. See the Rigify Log on the Metarig for more details.")
		else:
			self.report({'INFO'}, f"{rigs_generated} rig{'s' if rigs_generated>1 else ''} successfully generated!")

		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(Regenerate_Rigify_Rigs)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(Regenerate_Rigify_Rigs)