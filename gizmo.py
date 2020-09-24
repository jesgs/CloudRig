
import bpy

from bpy.types import (
	GizmoGroup,
	Gizmo,
)
from mathutils import Matrix


# -----------------------------------------------------------------------------
# Face-map gizmos

USE_VERBOSE = False

class IKPoleWidget(Gizmo):
	"""Widget to display when a cloud_ik_chain is selected."""
	#TODO: Maybe this can go in cloud_ik_chain.py at some point.
	bl_idname = "VIEW3D_WT_auto_facemap"

	__slots__ = (
		# PoseBone that owns the rig type.
		"rig_owner_bone",
		# List of all PoseBones belonging to the rig.
		"rig_bones",
		# Rig object the active pose bone belongs to.
		"rig_object",
	)

	def draw_bone(self, pose_bone, select_id=-1):
		matrix = pose_bone.matrix.copy()
		scale = Matrix.Scale(0.05, 4)
		matrix = matrix @ scale
		self.draw_preset_box(matrix, select_id=select_id)

	def draw(self, context):
		if USE_VERBOSE:
			print("(draw)")
		self.draw_bone(self.rig_owner_bone)

	def select_refresh(self):
		# XXX don't know what this does
		return
		fmap = getattr(self, "fmap", None)
		if fmap is not None:
			fmap.select = self.select

	def setup(self):
		if USE_VERBOSE:
			print("(setup)", self)

	def draw_select(self, context, select_id):
		if USE_VERBOSE:
			print("(draw_select)", self, context, select_id >> 8)
		self.draw_bone(self.rig_owner_bone, select_id)

	def invoke(self, context, event):
		if USE_VERBOSE:
			print("(invoke)", self, event)

		# XXX Don't get why this for loop is needed
		mpr_list = [self]
		for mpr in self.group.gizmos:
			if mpr is not self:
				if mpr.select:
					mpr_list.append(mpr)

		self.group.is_modal = True

		self.rig_owner_bone = context.active_pose_bone

		return {'RUNNING_MODAL'}

	def exit(self, context, cancel):
		self.group.is_modal = False

		if USE_VERBOSE:
			print("(exit)", self, cancel)

		if not cancel:
			bpy.ops.ed.undo_push(message="Tweak Gizmo")

	def modal(self, context, event, tweak):
		return {'RUNNING_MODAL'}

class CloudRigWidgetGroup(GizmoGroup):
	bl_idname = "POSE_WGT_cloudrig"
	bl_label = "CloudRig"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'WINDOW'
	bl_options = {'3D', 'DEPTH_3D', 'SELECT', 'PERSISTENT', 'SHOW_MODAL_ALL'}

	__slots__ = (
		# "widgets",
		# need some comparison
		"last_active_posebone",
		"is_modal",
	)

	@classmethod
	def poll(cls, context):
		return context.mode=='POSE' and context.active_pose_bone

	def setup_ik_pole_manipulator(self, rig_object, pose_bone):
		mpr = self.gizmos.new(IKPoleWidget.bl_idname)
		mpr.rig_owner_bone = pose_bone
		mpr.rig_object = rig_object

		mpr.alpha = 0.5

		mpr.color = 0.15, 0.62, 1.0
		mpr.color_highlight = mpr.color
		mpr.alpha_highlight = 0.5

		return mpr

	def setup(self, context):
		self.is_modal = False

		is_update = hasattr(self, "last_active_posebone")

		# For weak sanity check - detects undo
		if is_update and (self.last_active_posebone != context.active_pose_bone):
			is_update = False
			self.gizmos.clear()

		self.last_active_posebone = context.active_object

		def update():
			self.setup_ik_pole_manipulator(context.object, context.active_pose_bone)

		if not is_update:
			update()
		else:
			# first attempt simple update
			force_full_update = False
			# TODO: if rig owner bone is not the same as before: force_full_update=True
			
			if force_full_update:
				self.gizmos.clear()
				# same as above
				update()

	def refresh(self, context):
		if self.is_modal:
			return
		# WEAK!
		self.setup(context)

classes = (
	IKPoleWidget,
	CloudRigWidgetGroup,
)

def register():
	from bpy.utils import register_class
	for cls in classes:
		register_class(cls)


def unregister():
	from bpy.utils import unregister_class
	for cls in classes:
		unregister_class(cls)