import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix
import bgl

from bpy.app.handlers import persistent

import time

from .cloudrig import active_cloudrig
from .utils.mechanism import find_rig_of_bone
from . import rigs

# Dictionary holding previously selected rig's bones.
last_chain = []

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

def update_bone_group_highlighting(rig, rig_chain, last_chain):
	"""Make a bone group for rig element highlighting."""

	highlight_group = rig.pose.bone_groups.get('temp_highlight_group')
	if not highlight_group:
		highlight_group = rig.pose.bone_groups.new(name="temp_highlight_group")
		highlight_group.color_set = 'CUSTOM'

	if rig_chain == last_chain:
		return

	for b in rig.pose.bones:
		if not 'bone_group_backup' in b:
			if b.bone_group and b.bone_group.name=='temp_highlight_group':
				b.bone_group = None
			continue
		rig = b.id_data
		b.bone_group = rig.pose.bone_groups.get(b['bone_group_backup'])
		del b['bone_group_backup']

	last_chain = rig_chain
	for bone in rig_chain:
		if bone.bone_group and bone.bone_group.name!='temp_highlight_group':
			bone['bone_group_backup'] = bone.bone_group.name
		bone.bone_group = highlight_group

@persistent
def update_overlay():
	global last_chain

	refresh_time = 1/60

	context = bpy.context
	ob = context.object

	active_bone = context.active_pose_bone
	buffer.clear()

	if not (ob and active_bone and ob.type=='ARMATURE' and ob.mode in ['POSE']):	# TODO: Ideally, Edit mode would be supported, but it's a pain.
		return refresh_time

	rig_chain = find_rig_of_bone(active_bone)

	if rig_chain == None:
		return refresh_time

	rig_owner = rig_chain[0]

	if not hasattr(rigs, rig_owner.rigify_type):
		return refresh_time

	update_bone_group_highlighting(ob, rig_chain, last_chain)

	# Get the rig type's draw_overlay() function if it exists and execute it
	rig_module = getattr(rigs, rig_owner.rigify_type)
	rig_class = getattr(rig_module, 'Rig')
	if not hasattr(rig_class, 'draw_overlay'):
		return refresh_time
	lines = rig_class.draw_overlay(context, buffer)

	# Draw the buffer
	buffer.parent_object = ob
	buffer.draw_all()

	return refresh_time

@persistent
def load_handler(dummy):
	bpy.app.timers.register(update_overlay)

def register():
	buffer.clear()
	bpy.app.handlers.load_post.append(load_handler)

def unregister():
	buffer.clear()
	bpy.app.handlers.load_post.remove(load_handler)
	# bpy.app.timers.unregister(update_overlay) This doesn't seem neccessary...?