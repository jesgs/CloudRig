# TODO 4.0: Remove this dead file.

from bpy.types import DATA_PT_rigify_layer_names, VIEW3D_MT_rigify
import bpy

from ..generation.cloudrig import draw_layers_ui
from ..rig_component_features.ui import is_cloud_metarig, is_advanced_mode

def draw_rigify_header(self, context):
	layout = self.layout

	if not is_cloud_metarig(context.object):
		return self.draw_old(context)

	layout.operator('pose.cloudrig_generate', text="Generate")
	layout.operator('object.cloudrig_metarig_toggle')

	if context.mode == 'POSE':
		from rigify.operators.copy_mirror_parameters import draw_copy_mirror_ops
		draw_copy_mirror_ops(self, context)

	if context.mode == 'EDIT_ARMATURE':
		layout.separator()
		layout.operator('armature.metarig_sample_add')
		if is_advanced_mode(context):
			layout.separator()
			layout.operator('armature.rigify_encode_metarig', text="Encode Metarig")
			layout.operator('armature.rigify_encode_metarig_sample', text="Encode Metarig Sample")

def draw_cloud_layer_names(self, context):
	""" Hijack Rigify's Layer Names panel and replace it with our own. """
	obj = context.object
	# If the current rig doesn't have any cloudrig components, draw Rigify's UI.
	if not is_cloud_metarig(obj):
		bpy.types.DATA_PT_rigify_layer_names.draw_old(self, context)
		return

	arm = obj.data
	layout = self.layout

	# Ensure that the layers exist
	if len(arm.rigify_layers) != len(arm.layers):
		layout.operator('pose.cloudrig_layer_init')
		return

	# Layer Preview UI
	draw_layers_ui(layout, obj)

	# Layer Setup UI
	main_row = layout.row(align=True).split(factor=0.05)
	col_number = main_row.column()
	col_layer = main_row.column()

	for i in range(len(arm.rigify_layers)):
		if i in (0, 16):
			col_number.label(text="")
			text = ("Top" if i==0 else "Bottom") + " Row"
			row = col_layer.row()
			row.label(text=text)

		row = col_layer.row(align=True)
		col_number.label(text=str(i) + '.')
		rigify_layer = arm.rigify_layers[i]
		icon = 'RESTRICT_VIEW_OFF' if arm.layers[i] else 'RESTRICT_VIEW_ON'
		row.prop(arm, "layers", index=i, text="", toggle=True, icon=icon)
		icon = 'FAKE_USER_ON' if arm.layers_protected[i] else 'FAKE_USER_OFF'

		row.prop(rigify_layer, "name", text="")
		if rigify_layer.name:
			row.prop(rigify_layer, "row", text="UI Row")
		else:
			row.label(text="")

def register():
	# Hijack Rigify panels' draw functions.

	DATA_PT_rigify_layer_names.draw_old = DATA_PT_rigify_layer_names.draw
	DATA_PT_rigify_layer_names.draw = draw_cloud_layer_names

	VIEW3D_MT_rigify.draw_old = VIEW3D_MT_rigify.draw
	VIEW3D_MT_rigify.draw = draw_rigify_header


def unregister():
	# Restore Rigify panels' draw functions.
	try:
		DATA_PT_rigify_layer_names.draw = DATA_PT_rigify_layer_names.draw_old
		VIEW3D_MT_rigify.draw = VIEW3D_MT_rigify.draw_old
	except AttributeError:
		print("Warning: Looks like CloudRig never got registered?")