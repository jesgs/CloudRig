import bpy
from . import cloud_generator, actions
from rigify.utils.errors import MetarigError
from rigify.ui import rigify_report_exception
import traceback
from .cloudrig import draw_layers_ui

def is_cloud_metarig(rig):
	if rig.type=='ARMATURE' and 'rig_id' not in rig.data:
		for b in rig.pose.bones:
			if 'cloud' in b.rigify_type and b.rigify_type!='cloud_bone':
				return True
	return False


def draw_cloudrig_generator_settings(self, context):
	layout = self.layout
	layout.use_property_split=True
	layout.use_property_decorate=False
	layout = layout.column()

	obj = context.object
	cloudrig = obj.data.cloudrig_parameters

	layout.prop(obj.data, "rigify_target_rig")
	layout.prop(cloudrig, "custom_script")

	layout.prop(cloudrig, "create_root")
	if cloudrig.create_root:
		layout.prop(cloudrig, "double_root")

	layout.prop(cloudrig, "mechanism_selectable")
	if cloudrig.mechanism_selectable:
		layout.prop(cloudrig, "mechanism_movable")

	layout.prop(obj.data, "rigify_force_widget_update")

	layout.row().prop(cloudrig, "prefix_separator", expand=True)
	layout.row().prop(cloudrig, "suffix_separator", expand=True)

class CLOUDRIG_PT_actions(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = 'data'
	# bl_parent_id = 'DATA_PT_rigify_buttons'
	bl_label = "Rigify Actions"

	@classmethod
	def poll(cls, context):
		obj = context.object
		return is_cloud_metarig(context.object) and obj.mode in ('POSE', 'OBJECT')

	def draw(self, context):
		obj = context.object
		actions.draw_cloudrig_actions(self.layout, obj)

def draw_cloudrig_rigify_buttons(self, context):
	layout = self.layout
	obj = context.object

	if not is_cloud_metarig(context.object) or obj.mode=='EDIT':
		self.draw_old(context)
		return

	if obj.mode not in {'POSE', 'OBJECT'}:
		return

	layout.operator("pose.cloudrig_generate", text="Generate CloudRig")

	draw_cloudrig_generator_settings(self, context)
	
def draw_cloud_bone_group_options(self, context):
	""" Hijack Rigify's Bone Group panel and replace it with our own. """
	obj = context.object
	# If the current rig doesn't have any cloudrig elements, draw Rigify's UI.
	if not is_cloud_metarig(obj):
		bpy.types.DATA_PT_rigify_bone_groups.draw_old(self, context)
		return
	
	# Otherwise we draw our own.
	layout = self.layout
	layout.use_property_split=True
	layout.use_property_decorate=False
	layout = layout.column()

	layout.prop(obj.data, "rigify_colors_lock", text="Unified Select/Active Colors")
	if obj.data.rigify_colors_lock:
		layout.prop(obj.data.rigify_selection_colors, "select", text="Select Color")
		layout.prop(obj.data.rigify_selection_colors, "active", text="Active Color")

	cloudrig = obj.data.cloudrig_parameters
	layout.separator()

	dropdown = dropdown_ui(layout, cloudrig, "override_options")
	if dropdown:
	
		layout.prop_search(cloudrig, "root_bone_group", bpy.context.object.pose, "bone_groups")
		layout.prop(cloudrig, "root_layers", text="")

		if cloudrig.double_root:
			layout.prop_search(cloudrig, "root_parent_group", bpy.context.object.pose, "bone_groups")
			layout.prop(cloudrig, "root_parent_layers", text="")

		layout.separator()
		
		layout.prop(cloudrig, "override_def_layers")
		if cloudrig.override_def_layers:
			layout.prop(cloudrig, "def_layers", text="")

		layout.prop(cloudrig, "override_mch_layers")
		if cloudrig.override_mch_layers:
			layout.prop(cloudrig, "mch_layers", text="")

		layout.prop(cloudrig, "override_org_layers")
		if cloudrig.override_org_layers:
			layout.prop(cloudrig, "org_layers", text="")

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
			if i==16:
				layer.name = "IK Secondary"
			if i==1:
				layer.name = "FK"
				layer.row = 2
			if i==17:
				layer.name = "FK Secondary"
				layer.row = 2
			if i==2:
				layer.name = "Stretch"
				layer.row = 3

			if i==3:
				layer.name = "Face"
				layer.row = 4
			if i==19:
				layer.name = "Face Extras"
				layer.row = 4
			if i==20:
				layer.name = "Face Tweak"
				layer.row = 4

			if i==5:
				layer.name = "Fingers"
				layer.row = 5

			if i==6:
				layer.name = "Hair"
				layer.row = 6
			if i==7:
				layer.name = "Clothes"
				layer.row = 7


		return {'FINISHED'}

def draw_cloud_layer_names(self, context):
	""" Hijack Rigify's Layer Names panel and replace it with our own. """
	obj = context.object
	# If the current rig doesn't have any cloudrig elements, draw Rigify's UI.
	if not is_cloud_metarig(obj):
		bpy.types.DATA_PT_rigify_layer_names.draw_old(self, context)
		return
	
	obj = context.object
	arm = obj.data
	cloudrig = arm.cloudrig_parameters
	layout = self.layout
	ui_label_with_linebreak(layout, "Organize Layers panel layout. Layers without a name and layers beginning with $ will not be shown.")
	ui_label_with_linebreak(layout, "In the generated rig, the same layers will be active and protected as on the metarig.")

	# Ensure that the layers exist
	if len(arm.rigify_layers) != len(arm.layers):
		layout.operator('pose.cloudrig_layer_init')
		return

	# Layer Preview UI
	if dropdown_ui(layout, cloudrig, 'show_layers_preview'):
		draw_layers_ui(layout, obj)
		pass

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

class CLOUDRIG_OT_generate(bpy.types.Operator):
	"""Generates a rig from the active metarig armature using the CloudRig generator"""

	bl_idname = "pose.cloudrig_generate"
	bl_label = "CloudRig Generate Rig"
	bl_options = {'UNDO'}
	bl_description = 'Generates a rig from the active metarig armature using the CloudRig generator'

	def execute(self, context):
		try:
			cloud_generator.generate_rig(context, context.object)
		except MetarigError as rig_exception:
			traceback.print_exc()

			rigify_report_exception(self, rig_exception)
		except Exception as rig_exception:
			traceback.print_exc()

			self.report({'ERROR'}, 'Generation has thrown an exception: ' + str(rig_exception))
		finally:
			bpy.ops.object.mode_set(mode='OBJECT')

		return {'FINISHED'}

def ui_label_with_linebreak(layout, text):
	"""Attempt to simulate a proper textbox by only displaying as many characters in a single label as fits in the UI."""

	col = layout.column(align=True)
	paragraphs = text.split("\n")
	for p in paragraphs:
		words = p.split(" ")
		word_index = 0

		lines = [""]
		line_index = 0

		cur_line_length = 0
		# Try to determine maximum allowed characters in this line, based on pixel width of the area. 
		# Not a great metric, but I couldn't find anything better.
		max_line_length = bpy.context.area.width/8

		while word_index < len(words):
			word = words[word_index]

			if cur_line_length + len(word)+1 < max_line_length:
				word_index += 1
				cur_line_length += len(word)+1
				lines[line_index] += word + " "
			else:
				cur_line_length = 0
				line_index += 1
				lines.append("")
		
		for line in lines:
			col.label(text=line)

def dropdown_ui(layout, params, dropdown_param_name):
	is_dropdown_open = getattr(params, dropdown_param_name)

	icon = 'TRIA_DOWN' if is_dropdown_open else 'TRIA_RIGHT'
	row = layout.row()
	row.use_property_split=False
	row.alignment = 'LEFT'
	row.prop(params, dropdown_param_name, toggle=True, emboss=False, icon=icon)
	row.scale_y = 0.8
	if is_dropdown_open:
		# layout.separator()
		# box = layout.box()
		# box.scale_x = 2
		# box.alignment='EXPAND'
		return layout.column()
	return None

classes = [
	CLOUDRIG_OT_generate,
	CLOUDRIG_OT_layer_init,

	CLOUDRIG_PT_actions
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

	# Hijack Rigify panels' draw functions.
	bpy.types.DATA_PT_rigify_buttons.draw_old = bpy.types.DATA_PT_rigify_buttons.draw
	bpy.types.DATA_PT_rigify_buttons.draw = draw_cloudrig_rigify_buttons

	bpy.types.DATA_PT_rigify_bone_groups.draw_old = bpy.types.DATA_PT_rigify_bone_groups.draw
	bpy.types.DATA_PT_rigify_bone_groups.draw = draw_cloud_bone_group_options

	bpy.types.DATA_PT_rigify_layer_names.draw_old = bpy.types.DATA_PT_rigify_layer_names.draw
	bpy.types.DATA_PT_rigify_layer_names.draw = draw_cloud_layer_names

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)
	
	# Restore Rigify panels' draw functions.
	bpy.types.DATA_PT_rigify_buttons.draw = bpy.types.DATA_PT_rigify_buttons.draw_old
	bpy.types.DATA_PT_rigify_bone_groups.draw = bpy.types.DATA_PT_rigify_bone_groups.draw_old
	bpy.types.DATA_PT_rigify_layer_names.draw = bpy.types.DATA_PT_rigify_layer_names.draw_old