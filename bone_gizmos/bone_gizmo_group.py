import bpy
from typing import Dict, Tuple, List
from bpy.types import GizmoGroup, Object, PoseBone
from bpy.app.handlers import persistent

class CloudGizmoGroup(GizmoGroup):
	"""This single GizmoGroup manages all CloudRig gizmos for all rigs."""	# TODO: Currently this will have issues when there are two rigs with similar bone names. Rig object names should be included when identifying widgets.
	bl_idname = "OBJECT_GGT_cloudrig_gizmo"
	bl_label = "CloudRig Gizmos"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'WINDOW'
	bl_options = {
		'3D'				# Lets Gizmos use the 'draw_select' function to draw into a selection pass.
		,'PERSISTENT'
		,'SHOW_MODAL_ALL'	# TODO what is this
		,'DEPTH_3D'			# Provides occlusion but results in Z-fighting when using the face map preset function.
		,'SELECT'			# I thought this would make Gizmo.select do something but doesn't seem that way
		,'SCALE'			# This makes all gizmos' scale relative to the world rather than the camera, so we don't need to set use_draw_scale on each Gizmo. (And that option does nothing because of this one)
	}

	@classmethod
	def poll(cls, context):
		return context.scene.cloud_gizmos_enabled and context.object \
			and context.object.type == 'ARMATURE' and context.object.mode=='POSE'

	def setup(self, context):
		"""Executed by Blender or by gizmo updates. We create all gizmos here,
		so between calls to this, all gizmos should first be destroyed."""
		self.widgets = {}
		for pose_bone in context.object.pose.bones:
			if pose_bone.cloudrig_gizmo.enabled:
				gizmo = self.create_gizmo(context, pose_bone)
				self.widgets[pose_bone.name] = gizmo

	def create_gizmo(self, context, pose_bone):
		"""Add a gizmo to this GizmoGroup based on user-defined properties."""
		gizmo_props = pose_bone.cloudrig_gizmo

		if not gizmo_props.enabled:
			return
		gizmo = self.gizmos.new('GIZMO_GT_cloudrig_bone')
		gizmo.props = gizmo_props
		gizmo.target_set_operator(gizmo_props.operator)
		gizmo.gizmo_group = self
		gizmo.bone_name = pose_bone.name
		gizmo.init_shape(context)
		gizmo.init_properties()

		return gizmo

	def refresh(self, context):
		"""This is a Gizmo API function, called by Blender on what seems to be
		depsgraph updates and frame changes.
		Refresh all visible gizmos that use vertex group masking.
		This should be done whenever a bone position changes.
		This should be kept performant!
		"""
		dg = bpy.context.evaluated_depsgraph_get()
		eval_meshes = {}

		for bonename, gizmo in self.widgets.items():
			if not gizmo or not gizmo.is_using_vgroup() or not gizmo.poll(context):
				continue

			obj = gizmo.props.shape_object
			if obj.name in eval_meshes:
				eval_mesh = eval_meshes[obj.name]
			else:
				eval_meshes[obj.name] = eval_mesh = obj.evaluated_get(dg).to_mesh()
				eval_mesh.calc_loop_triangles()
			gizmo.refresh_shape_vgroup(context, eval_mesh)

classes = (
	CloudGizmoGroup,
)

# To ensure that things update properly, we re-register the GizmoGroup whenever
# a gizmo property changes. TODO: Maybe this is not necessary, but it probably is though.
_register, _unregister = bpy.utils.register_classes_factory(classes)

@persistent
def update_gizmos(self, context):
	"""This should be called whenever a gizmo setting is modified by user, to make
	sure that those settings changes actually apply to the relevant gizmo."""
	# TODO: This is obviously incredibly slow.
	if context == None:
		context = bpy.context
	unregister()
	if context.scene.cloud_gizmos_enabled:
		_register()

def register():
	_register()
	bpy.app.handlers.undo_post.append(update_gizmos)

def unregister():
	try:
		_unregister()
	except RuntimeError:
		pass
