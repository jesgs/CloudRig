import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix
import bgl

from bpy.app.handlers import persistent

import time

from .cloudrig import active_cloudrig
from . import rigs

def dpifac():
	prefs = bpy.context.preferences.system
	return prefs.dpi * prefs.pixel_size / 72

class Line:
	def __init__(self, vec1, vec2, size=1, color=(1.0, 1.0, 1.0, 1.0)):
		self.vec1 = vec1
		self.vec2 = vec2
		self.size = size
		self.color = color

class RenderBuffer:
	"""Keep track of things to draw, before actually drawing them.

	The goal is to get similar behaviour as what the PyAPI already does with 
	Blender's UI drawing. A UILayout object is passed to all draw() functions, 
	and from in there, we call functions on it to add UI elements.

	A RenderBuffer object instance is created in load_handler(), and passed
	to all CloudRig rig types' draw_overlay() functions, where they can draw
	whatever they want. 
	
	The implementation provides an abstraction layer top of the PyAPI's gpu 
	module, just to keep the code in the draw_overlay()	functions nice and clean.

	We currently only create one RenderBuffer instance, but you could create
	multiple instances, like drawing groups of elements separately and then only
	re-draw each group when needed.
	"""
	def __init__(self, parent_object = None):
		self.all_elements = []
		self.all_handlers = []
		self.lines = []

		self.parent_object = parent_object
	
	def draw_line_3d(self, vec1, vec2, size=3, color=(1.0, 1.0, 0.0, 1.0)):
		self.lines.append(Line(vec1.copy(), vec2.copy(), size, color))

	@staticmethod
	def real_draw_line_3d(vec1, vec2, size=3, color=(1.0, 1.0, 1.0, 1.0)):
		shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')

		vertices = (vec1, vec2)
		batch = batch_for_shader(shader, 'LINES', {"pos": vertices})
		bgl.glLineWidth(size * dpifac())

		shader.bind()
		shader.uniform_float("color", color)
		batch.draw(shader)

	def draw_all(self):
		for line in self.lines:
			points = (line.vec1, line.vec2)
			
			# TODO: This code doesn't really belong here. It can go in utilities/math or so, and then called from each rigs' draw_overlay(). Otherwise, if a rig wanted to draw an overlay that isn't parented to the armature object, it couldn't... although, maybe that's fine... HMMM....
			if self.parent_object:
				line_matrix = ( Matrix.Translation(line.vec1),
								Matrix.Translation(line.vec2) )
				line_transformed_matrix = ( line_matrix[0] @ self.parent_object.matrix_world,
											line_matrix[1] @ self.parent_object.matrix_world)

				points = (line_transformed_matrix[0].to_translation(),
						  line_transformed_matrix[1].to_translation())

			handler = bpy.types.SpaceView3D.draw_handler_add(self.real_draw_line_3d, (points[0], points[1], line.size, line.color), 'WINDOW', 'POST_VIEW')
			self.all_handlers.append(handler)

	def clear(self):
		for handler in self.all_handlers[:]:
			bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
			self.all_handlers.remove(handler)
		self.lines = []

buffer = RenderBuffer()
last_active_pose_bone = ""

@persistent
def update_overlay():
	global last_active_pose_bone

	refresh_time = 1/60

	context = bpy.context
	ob = context.object

	active_pb = context.active_pose_bone

	if not active_pb:
		buffer.clear()
		last_active_pose_bone = ""
		return refresh_time

	if active_pb.name == last_active_pose_bone:
		buffer.clear()
		# return refresh_time

	if active_pb.name != last_active_pose_bone:
		last_active_pose_bone = active_pb.name
		buffer.clear()

	if not hasattr(active_pb, 'rigify_type') or not hasattr(rigs, active_pb['rigify_type']):
		return refresh_time

	# Get the CloudRig rig type
	rig_module = getattr(rigs, active_pb['rigify_type'])
	rig_class = getattr(rig_module, 'Rig')
	if not hasattr(rig_class, 'draw_overlay'):
		return refresh_time

	# Execute the rig's draw function to get what it wants to draw - For now we just support lines.
	lines = rig_class.draw_overlay(context, buffer)
	
	buffer.parent_object = ob
	buffer.draw_all()

	return refresh_time

@persistent
def load_handler(dummy):
	bpy.app.timers.register(update_overlay)

def register():
	print("Registering CloudRig overlay.")
	buffer.clear()
	bpy.app.handlers.load_post.append(load_handler)

def unregister():
	buffer.clear()
	bpy.app.handlers.load_post.remove(load_handler)
	# bpy.app.timers.unregister(update_overlay) This doesn't seem neccessary...?