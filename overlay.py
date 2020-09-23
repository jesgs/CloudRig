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

def draw_line_3d(vec1, vec2, size=3, color=(1.0, 1.0, 1.0, 0.7)):
	shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')

	vertices = (vec1, vec2)

	# vertices = ((x1, y1), (x2, y2))
	# vertex_colors = ((color[0]+(1.0-color[0])/4,
	# 				  color[1]+(1.0-color[1])/4,
	# 				  color[2]+(1.0-color[2])/4,
	# 				  color[3]+(1.0-color[3])/4),
	# 				  color)

	batch = batch_for_shader(shader, 'LINES', {"pos": vertices})
	# batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": vertices, "color": vertex_colors})
	bgl.glLineWidth(size * dpifac())

	shader.bind()
	shader.uniform_float("color", (1, 1, 0, 1))
	batch.draw(shader)

time_since_last_draw = 0
last_active_pose_bone = ""
active_draw_handlers = []

def remove_overlays():
	global active_draw_handlers
	for draw_handler in active_draw_handlers[:]:
		bpy.types.SpaceView3D.draw_handler_remove(draw_handler, 'WINDOW')
		active_draw_handlers.remove(draw_handler)

@persistent
def update_overlay():
	global time_since_last_draw
	global last_active_pose_bone
	global active_draw_handlers

	refresh_time = 1/60

	context = bpy.context
	ob = context.object

	active_pb = context.active_pose_bone

	if not active_pb:
		remove_overlays()
		last_active_pose_bone = ""
		return refresh_time

	if active_pb.name == last_active_pose_bone:
		remove_overlays()
		# return refresh_time

	if active_pb.name != last_active_pose_bone:
		last_active_pose_bone = active_pb.name
		remove_overlays()

	if not hasattr(active_pb, 'rigify_type') or not hasattr(rigs, active_pb['rigify_type']):
		return refresh_time

	# Get the CloudRig rig type
	rig_module = getattr(rigs, active_pb['rigify_type'])
	rig_class = getattr(rig_module, 'Rig')
	if not hasattr(rig_class, 'draw_overlay'):
		return refresh_time

	# Execute the rig's draw function to get what it wants to draw - For now we just support lines.
	lines = rig_class.draw_overlay(context)

	for line in lines:
		line_matrix = ( Matrix.Translation(line[0]),
						Matrix.Translation(line[1]) )
		line_transformed_matrix = (line_matrix[0] @ ob.matrix_world,
							line_matrix[1] @ ob.matrix_world)

		line_transformed = (line_transformed_matrix[0].to_translation(),
							line_transformed_matrix[1].to_translation())

		handler = bpy.types.SpaceView3D.draw_handler_add(draw_line_3d, (line_transformed[0], line_transformed[1]), 'WINDOW', 'POST_VIEW')
		active_draw_handlers.append(handler)

	return refresh_time

@persistent
def load_handler(dummy):
	bpy.app.timers.register(update_overlay)

def register():
	print("Registering CloudRig overlay.")
	remove_overlays()
	bpy.app.handlers.load_post.append(load_handler)

def unregister():
	remove_overlays()
	bpy.app.handlers.load_post.remove(load_handler)
	# bpy.app.timers.unregister(update_overlay) This doesn't seem neccessary...?