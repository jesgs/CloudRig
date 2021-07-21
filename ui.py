# This module shouldn't need to be imported anywhere else.
# Such things would belong in CloudRig/utils/ui.py.

import bpy
import addon_utils

from rigify import rig_lists
from rigify import feature_sets

from .cloudrig import draw_layers_ui
from .utils.ui import draw_label_with_linebreak, is_cloud_metarig


# NOTE: STRICTLY NOT ALLOWED TO IMPORT RIG CLASSES! RESULTS IN IMPOSSIBLE TO TROUBLESHOOT ERRORS!

class CLOUDRIG_OT_layer_init(bpy.types.Operator):
	"""Initialize armature rigify layers"""

	bl_idname = "pose.cloudrig_layer_init"
	bl_label = "Add Rigify Layers (CloudRig)"
	bl_options = {'UNDO', 'INTERNAL'}

	def execute(self, context):
		obj = context.object
		arm = obj.data
		for i in range(len(arm.rigify_layers), len(arm.layers)):
			layer = arm.rigify_layers.add()

			if i==0:
				layer.name = "IK"
			elif i==16:
				layer.name = "IK Secondary"
			elif i==1:
				layer.name = "FK"
				layer.row = 2
			elif i==17:
				layer.name = "FK Secondary"
				layer.row = 2
			elif i==2:
				layer.name = "Stretch"
				layer.row = 3

			elif i==3:
				layer.name = "Face"
				layer.row = 4
			elif i==19:
				layer.name = "Face Extras"
				layer.row = 4
			elif i==20:
				layer.name = "Face Tweak"
				layer.row = 4

			elif i==5:
				layer.name = "Fingers"
				layer.row = 5

			elif i==6:
				layer.name = "Hair"
				layer.row = 6
			elif i==7:
				layer.name = "Clothes"
				layer.row = 7

			elif i==29:
				layer.name = "$DEF"
				layer.row = 32
			elif i==30:
				layer.name = "$MCH"
				layer.row = 32
			elif i==31:
				layer.name = "$ORG"
				layer.row = 32
			else:
				layer.name = ""

		return {'FINISHED'}

def draw_cloudrig_rigify_generate(self, context):
	layout = self.layout
	obj = context.object

	if not is_cloud_metarig(context.object) or obj.mode=='EDIT':
		self.draw_old(context)
		return

	if obj.mode not in {'POSE', 'OBJECT'}:
		return

	# Compare Blender version number to current lowest supported
	# version number. If Blender is too old, provide a link to download
	# an older version of CloudRig.
	version_to_float = lambda version_tuple: float(str(version_tuple[0]) + "." + str(version_tuple[1]) + str(version_tuple[2]))

	blender_version = version_to_float(bpy.app.version)
	cloudrig_module = getattr(feature_sets, __package__.replace("rigify.feature_sets.", ""))
	lowest_compatible_version = version_to_float(cloudrig_module.rigify_info['blender'])
	is_compatible = blender_version <= lowest_compatible_version

	if not is_compatible:
		draw_label_with_linebreak(layout, f"This version of CloudRig requires at least Blender {blender_version}.", alert=True)
		draw_label_with_linebreak(layout, f"You can download an older version of CloudRig from the Releases page on CloudRig's GitLab:", alert=True)
		op = layout.operator('wm.url_open', text="Releases", icon='URL')
		op.url = "https://gitlab.com/blender/CloudRig/-/releases"
		return

	layout.operator("pose.cloudrig_generate", text="Generate CloudRig")

	draw_cloudrig_generator_settings(self, context)

def metarig_contains_fk_chain(metarig):
	"""Return whether or not a metarig contains an FK rig. Used to determine
	whether animation generation checkbox should appear or not."""
	for pb in metarig.pose.bones:
		if pb.rigify_type!='':
			rig_module = rig_lists.rigs[pb.rigify_type]["module"].Rig
			# This is a bit nasty but importing CloudFKCHainRig and using issubclass() breaks parameter registering (don't ask me why!)
			if 'cloud_fk_chain' in str(rig_module.mro()):
				return True

def draw_cloudrig_generator_settings(self, context):
	layout = self.layout
	layout.use_property_split=True
	layout.use_property_decorate=False
	layout = layout.column()

	obj = context.object
	cloudrig = obj.data.cloudrig_parameters

	# Basic Parameters
	layout.prop(obj.data, "rigify_target_rig")
	layout.prop(obj.data, "rigify_rig_ui")
	layout.prop(cloudrig, "custom_script")
	layout.prop(cloudrig, "widget_collection")

	layout.separator()

	# Bone Group Color Parameters
	layout.prop(obj.data, "rigify_colors_lock", text="Unified Select/Active Colors")
	if obj.data.rigify_colors_lock:
		layout.prop(obj.data.rigify_selection_colors, "select", text="Select Color")
		layout.prop(obj.data.rigify_selection_colors, "active", text="Active Color")

	layout.separator()

	# Test Animation Parameters
	if metarig_contains_fk_chain(obj):
		heading = "Generate Action"
		if cloudrig.test_action:
			heading = "Update Action"
		act_row = layout.row(heading=heading)
		act_row.prop(cloudrig, 'generate_test_action', text="")
		act_col = act_row.column()
		act_col.prop(cloudrig, 'test_action', text="")
		act_col.enabled = cloudrig.generate_test_action

	layout.separator()

	### Root Bone Parameters
	layout.prop(cloudrig, 'create_root')
	if cloudrig.create_root:
		layout.prop_search(cloudrig, "root_bone_group", context.object.pose, "bone_groups")
		row = layout.row()
		row.use_property_split=False
		row.prop(cloudrig, "root_layers", text="")
		layout.prop(cloudrig, 'double_root')
		if cloudrig.double_root:
			layout.prop_search(cloudrig, "root_parent_group", context.object.pose, "bone_groups")
			row = layout.row()
			row.use_property_split=False
			row.prop(cloudrig, "root_parent_layers", text="")

	layout.separator()

	# Advanced Parameters
	layout.prop(obj.data, 'rigify_force_widget_update')

@classmethod
def rigify_bone_groups_poll(cls, context):
	# If the current rig has any cloudrig elements, don't draw this panel.
	if is_cloud_metarig(context.object):
		return
	return bpy.types.DATA_PT_rigify_bone_groups.poll_old(context)

def draw_cloud_layer_names(self, context):
	""" Hijack Rigify's Layer Names panel and replace it with our own. """
	obj = context.object
	# If the current rig doesn't have any cloudrig elements, draw Rigify's UI.
	if not is_cloud_metarig(obj):
		bpy.types.DATA_PT_rigify_layer_names.draw_old(self, context)
		return

	arm = obj.data
	cloudrig = arm.cloudrig_parameters
	layout = self.layout
	draw_label_with_linebreak(layout, "Organize Layers panel layout. Layers without a name and layers beginning with $ will not be shown.")
	draw_label_with_linebreak(layout, "In the generated rig, the same layers will be active and protected as on the metarig.")

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
		col_number.label(text=str(i+1) + '.')
		rigify_layer = arm.rigify_layers[i]
		icon = 'RESTRICT_VIEW_OFF' if arm.layers[i] else 'RESTRICT_VIEW_ON'
		row.prop(arm, "layers", index=i, text="", toggle=True, icon=icon)
		icon = 'FAKE_USER_ON' if arm.layers_protected[i] else 'FAKE_USER_OFF'

		row.prop(arm, "layers_protected", index=i, text="", toggle=True, icon=icon)
		row.prop(rigify_layer, "name", text="")
		row.prop(rigify_layer, "row", text="UI Row")

		if addon_utils.check('bone_selection_sets')[1]:
			icon = 'RADIOBUT_ON' if rigify_layer.selset else 'RADIOBUT_OFF'
			row.prop(rigify_layer, "selset", text="", toggle=True, icon=icon)

classes = [
	CLOUDRIG_OT_layer_init
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

	# Hijack Rigify panels' draw functions.
	if hasattr(bpy.types, 'DATA_PT_rigify_buttons'):	# TODO: Remove when dropping Blender 3.0 compatibility.
		rigify_generate_ui = bpy.types.DATA_PT_rigify_buttons
	else:
		rigify_generate_ui = bpy.types.DATA_PT_rigify_generate

	rigify_generate_ui.draw_old = rigify_generate_ui.draw
	rigify_generate_ui.draw = draw_cloudrig_rigify_generate

	bpy.types.DATA_PT_rigify_bone_groups.poll_old = bpy.types.DATA_PT_rigify_bone_groups.poll
	bpy.types.DATA_PT_rigify_bone_groups.poll = rigify_bone_groups_poll

	bpy.types.DATA_PT_rigify_layer_names.draw_old = bpy.types.DATA_PT_rigify_layer_names.draw
	bpy.types.DATA_PT_rigify_layer_names.draw = draw_cloud_layer_names

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)

	# Restore Rigify panels' draw functions.
	if hasattr(bpy.types, 'DATA_PT_rigify_buttons'):	# TODO: Remove when dropping Blender 3.0 compatibility.
		rigify_generate_ui = bpy.types.DATA_PT_rigify_buttons
	else:
		rigify_generate_ui = bpy.types.DATA_PT_rigify_generate
	rigify_generate_ui.draw = rigify_generate_ui.draw_old
	bpy.types.DATA_PT_rigify_bone_groups.poll = bpy.types.DATA_PT_rigify_bone_groups.poll_old
	bpy.types.DATA_PT_rigify_layer_names.draw = bpy.types.DATA_PT_rigify_layer_names.draw_old