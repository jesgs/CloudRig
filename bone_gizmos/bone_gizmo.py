import bpy
from bpy.types import Gizmo, Object
import numpy as np
import gpu

class MoveBoneGizmo(Gizmo):
	"""In order to avoid re-implementing logic for transforming bones with 
	mouse movements, this gizmo instead binds its offset value to the
	bpy.ops.transform.translate operator, giving us all that behaviour for free.
	(Important behaviours like auto-keying, precision, snapping, axis locking, etc)
	The downside of this is that we can't customize that behaviour very well,
	for example we can't get the gizmo to draw during mouse interaction.
	"""

	bl_idname = "GIZMO_GT_cloudrig_bone"
	# The id must be "offset"
	bl_target_properties = (
		{"id": "offset", "type": 'FLOAT', "array_length": 3},
	)

	__slots__ = (
		# This __slots__ thing allows us to use arbitrary Python variable 
		# assignments on instances of this gizmo.
		"bone_name",	# Name of the bone that owns this gizmo.
		"props",		# instance of CloudGizmoProperties that's stored on the bone that owns this gizmo.

		# Extra attribtues used for insteraction
		"custom_shape",
		"init_mouse",
		"init_value",

		"color_backup",
		"alpha_backup"
	)

	def setup(self):
		"""Called by Blender when the Gizmo is created."""
		self.target_set_operator("transform.translate")

	def poll(self, context):
		"""Whether any gizmo logic should be executed or not. This function is not
		from the API! Call and override this function liberally to prevent logic execution.
		"""
		pb = self.get_pose_bone(context)
		return pb and not pb.bone.hide and self.props.shape_object and self.props.enabled

	def ensure_custom_shape(self, context):
		if hasattr(self, "custom_shape"):
			return

		mesh = self.props.shape_object.data
		vertices = np.zeros((len(mesh.vertices), 3), 'f')
		mesh.vertices.foreach_get("co", vertices.ravel())

		if self.props.draw_style == 'POINTS':
			custom_shape_verts = vertices

		elif self.props.draw_style == 'LINES':
			edges = np.zeros((len(mesh.edges), 2), 'i')
			mesh.edges.foreach_get("vertices", edges.ravel())
			custom_shape_verts = vertices[edges].reshape(-1,3)

		elif self.props.draw_style == 'TRIS':
			mesh.calc_loop_triangles()
			tris = np.zeros((len(mesh.loop_triangles), 3), 'i')
			mesh.loop_triangles.foreach_get("vertices", tris.ravel())
			custom_shape_verts = vertices[tris].reshape(-1,3)

		self.custom_shape = self.new_custom_shape(self.props.draw_style, custom_shape_verts)

	def draw_shape(self, context, select_id=None):
		"""Shared drawing logic for selection and color.
		The actual color seems to be determined deeper, between self.color and self.color_highlight.
		"""

		face_map = self.props.shape_object.face_maps.get(self.props.face_map_name)
		if not face_map:
			self.draw_custom_shape(self.custom_shape, select_id=select_id)
		else:
			self.draw_preset_facemap(self.props.shape_object, face_map.index, select_id=select_id or 0)

	def draw_shared(self, context, select_id=None):
		if not self.poll(context):
			return
		if not self.props.shape_object:
			return
		self.ensure_custom_shape(context)
		self.update_offset_matrix(context)

		gpu.state.line_width_set(self.line_width)
		gpu.state.blend_set('MULTIPLY')
		self.draw_shape(context, select_id)
		gpu.state.blend_set('NONE')
		gpu.state.line_width_set(1)

	def draw(self, context):
		"""Called by Blender on every viewport update (including mouse moves).
		Drawing functions called at this time will draw into the color pass.
		"""
		if not self.poll(context):
			return
		if self.use_draw_hover and not self.is_highlight:
			return

		pb = self.get_pose_bone(context)
		if pb.bone.select and not self.select:
			# If the bone just got selected, swap the colors.
			self.color_backup = self.color.copy()
			self.alpha_backup = self.alpha
			self.color = self.color_highlight
			self.alpha = self.alpha_highlight
		elif self.select and not pb.bone.select and hasattr(self, 'color_backup'):
			# If the bone just got unselected, swap the colors back.
			self.color = self.color_backup.copy()
			self.alpha = self.alpha_backup

		self.select = pb.bone.select
		self.draw_shared(context)

	def draw_select(self, context, select_id):
		"""Called by Blender on every viewport update (including mouse moves).
		Drawing functions called at this time will draw into an invisible pass
		that is used for mouse interaction.
		"""
		if not self.poll(context):
			return
		self.draw_shared(context, select_id)

	def get_pose_bone(self, context):
		return context.object.pose.bones.get(self.bone_name)

	def update_offset_matrix(self, context):
		armature = context.object
		pb = self.get_pose_bone(context)
		assert armature and pb, "update_offset_matrix shouldn't be called until a valid armature and pose bone are specified."

		ob_mat = armature.matrix_world
		self.matrix_basis = ob_mat @ pb.bone.matrix_local
		self.matrix_offset = pb.matrix_basis

	def invoke(self, context, event):
		armature = context.object
		if not event.shift:
			for pb in armature.pose.bones:
				pb.bone.select = False
		pb = self.get_pose_bone(context)
		pb.bone.select = True
		armature.data.bones.active = pb.bone
		return {'RUNNING_MODAL'}

	def exit(self, context, cancel):
		return

	def modal(self, context, event, tweak):
		return {'RUNNING_MODAL'}

classes = (
	MoveBoneGizmo,
)

register, unregister = bpy.utils.register_classes_factory(classes)
