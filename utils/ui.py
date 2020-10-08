import bpy
import json
from ..cloudrig import draw_layers_ui
from rigify.ui import rigify_report_exception

class CloudUIMixin:
	forced_params = dict()

	def add_ui_data(self, ui_area, row_name, col_name, info, **custom_property_dict):
		add_ui_data(self.obj, ui_area, row_name, col_name.replace("_", " "), info, **custom_property_dict)

	@classmethod
	def draw_prop(cls, layout, prop_owner, prop_name, new_row=True, **kwargs):
		row = draw_prop(layout, prop_owner, prop_name, new_row, **kwargs)
		if prop_name in cls.forced_params.keys():
			row.enabled = False
		return row

	@classmethod
	def draw_prop_search(cls, layout, prop_owner, prop_name, collection, coll_prop_name, new_row=True, **kwargs):
		row = draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, new_row, **kwargs)
		if prop_name in cls.forced_params.keys():
			row.enabled = False

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		doc = cls.__doc__ or cls.__bases__[0].__doc__
		if doc:
			draw_label_with_linebreak(layout, doc)

		layout.use_property_split = True
		layout.use_property_decorate = False
		col = layout.column()
		return col

	@classmethod
	def draw_dropdown_menu(cls, layout, params, dropdown_param_name, alert=False):
		layout.separator()
		return draw_dropdown(layout, params, dropdown_param_name, alert)

	@classmethod
	def draw_bone_set_params(cls, layout, params, set_info):
		obj = bpy.context.object
		cloudrig = obj.data.cloudrig_parameters
		if set_info['override'] == 'DEF' and cloudrig.override_def_layers: return
		if set_info['override'] == 'MCH' and cloudrig.override_mch_layers: return
		if set_info['override'] == 'ORG' and cloudrig.override_org_layers: return

		col = layout.column()
		col.use_property_split=True
		cls.draw_prop_search(col, params, set_info['param'], obj.pose, "bone_groups", new_row=False, text=set_info['name'])

		if True:
			layout.use_property_split=False
			draw_layers_ui(layout, obj, show_hidden=cloudrig.show_layers_preview_hidden, owner=params, layers_prop = set_info['layer_param'])
			# TODO: This results in a pretty massive piece of UI. Might be nicer as a UIList, but not sure if possible?
		else:
			row = col.row()
			row.use_property_split=False
			cls.draw_prop(row, params, set_info['layer_param'], text="")
		layout.separator()

	@classmethod
	def draw_bone_sets_params(cls, layout, params):
		if not cls.draw_dropdown_menu(layout, params, 'CR_show_bone_sets'): return

		obj = bpy.context.object

		cloudrig = obj.data.cloudrig_parameters
		layout.prop(cloudrig, 'show_layers_preview_hidden')

		for ui_name in cls.bone_set_defs.keys():
			set_info = cls.bone_set_defs[ui_name]
			cls.draw_bone_set_params(layout, params, set_info)

def is_cloud_metarig(rig):
	if rig.type=='ARMATURE' and 'rig_id' not in rig.data:
		for b in rig.pose.bones:
			if 'cloud' in b.rigify_type and b.rigify_type!='cloud_bone':
				return True
	return False

def draw_label_with_linebreak(layout, text):
	""" Attempt to simulate a proper textbox by only displaying as many 
		characters in a single label as fits in the UI.
		This only works well on specific UI zoom levels.
	"""

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

def draw_prop(layout, prop_owner, prop_name, new_row=True, **kwargs):
	if new_row:
		layout = layout.row()
	layout.prop(prop_owner, prop_name, **kwargs)
	return layout

def draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, new_row, **kwargs):
	if new_row:
		layout = layout.row()
	layout.prop_search(prop_owner, prop_name, collection, coll_prop_name, **kwargs)
	return layout

def draw_dropdown(layout, params, dropdown_param_name, alert=False):
	is_dropdown_open = getattr(params, dropdown_param_name)

	icon = 'TRIA_DOWN' if is_dropdown_open else 'TRIA_RIGHT'
	row = layout.row()
	row.use_property_split=False
	row.alignment = 'LEFT'
	row.prop(params, dropdown_param_name, toggle=True, emboss=False, icon=icon)
	if alert:
		row.prop(params, dropdown_param_name, text="", toggle=True, emboss=False, icon='ERROR')
	row.scale_y = 0.8
	if is_dropdown_open:
		return layout
	return None

def add_ui_data(obj, ui_area, row_name, col_name, info, **custom_prop_dict):
	"""Store a dict in the rig data, which is used by cloudrig.py to draw the CloudRig UI.
	ui_area: One of a list of pre-defined strings that the UI script
				recognizes, that describes a panel or area in the UI.
				Eg, "fk_hinges", "ik_switches".
	row_name: A row in the UI area.
	col_name: A column within the row.
	info: The dictionary to store in the rig data.
	"""

	assert ('prop_bone' in info) and ('prop_id' in info), 'Expected an info dict with at least "prop_bone" and "prop_id" keys.'

	for key in info.keys():
		value = info[key]
		if type(value) in (list, dict):
			info[key] = json.dumps(value)

	if ui_area not in obj.data:
		obj.data[ui_area] = {}

	if row_name not in obj.data[ui_area]:
		obj.data[ui_area][row_name] = {}

	prop_bone = info['prop_bone']
	info['prop_bone'] = prop_bone.name
	obj.data[ui_area][row_name][col_name] = info

	# Create custom property.
	prop_id = info['prop_id']
	if 'default' not in custom_prop_dict:
		custom_prop_dict['default'] = 0.0
	prop_bone.custom_props[prop_id] = custom_prop_dict