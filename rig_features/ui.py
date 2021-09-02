from .bone import BoneInfo

import bpy, sys, os
import json

class CloudUIMixin:
	forced_params = dict()

	def add_ui_data(self, panel_name, row_name, info, *, label_name="", entry_name="", **custom_prop_dict):
		add_ui_data(self.obj, panel_name, row_name, info, entry_name, label_name, **custom_prop_dict)

	@staticmethod
	def draw_control_label(layout, text=""):
		split = layout.split(factor=0.4)
		split.row()
		split.label(text=text+":")

	@staticmethod
	def is_advanced_mode(context):
		return is_advanced_mode(context)

	@classmethod
	def draw_prop(cls, layout, prop_owner, prop_name, new_row=True, **kwargs):
		if prop_name in cls.forced_params.keys():
			return layout
		row = draw_prop(layout, prop_owner, prop_name, new_row, **kwargs)
		return row

	@classmethod
	def draw_prop_search(cls, layout, prop_owner, prop_name, collection, coll_prop_name, new_row=True, **kwargs):
		row = draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, new_row, **kwargs)
		if prop_name in cls.forced_params.keys():
			row.enabled = False
		return row

def is_advanced_mode(context):
	if not is_cloud_metarig(context.object):
		return False
	return context.object.data.cloudrig_parameters.advanced_mode

def is_cloud_metarig(rig):
	if rig.type=='ARMATURE' and 'rig_id' not in rig.data:
		for b in rig.pose.bones:
			if 'cloud' in b.rigify_type:
				return True
	return False

def draw_label_with_linebreak(layout, text, alert=False, align_split=False):
	""" Attempt to simulate a proper textbox by only displaying as many
		characters in a single label as fits in the UI.
		This only works well on specific UI zoom levels.
	"""

	if text=="": return
	col = layout.column(align=True)
	col.alert = alert
	if align_split:
		split = col.split(factor=0.2)
		split.row()
		col = split.row().column()
	paragraphs = text.split("\n")

	# Try to determine maximum allowed characters per line, based on pixel width of the area.
	# Not a great metric, but I couldn't find anything better.
	max_line_length = bpy.context.area.width/8
	if align_split:
		max_line_length *= 0.95
	for p in paragraphs:

		lines = [""]
		for word in p.split(" "):
			if len(lines[-1]) + len(word)+1 > max_line_length:
				lines.append("")
			lines[-1] += word + " "

		for line in lines:
			col.label(text=line)
	return col

def draw_prop(layout, prop_owner, prop_name, new_row=True, **kwargs):
	if new_row:
		layout = layout.row(align=True)
	layout.prop(prop_owner, prop_name, **kwargs)
	return layout

def draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, new_row, **kwargs):
	if new_row:
		layout = layout.row()
	layout.prop_search(prop_owner, prop_name, collection, coll_prop_name, **kwargs)
	return layout

def add_ui_data(obj, panel_name, row_name, info, entry_name="", label_name="", parent_id="", **custom_prop_dict):
	"""Store a dict in the rig data, which is used by cloudrig.py to draw the CloudRig UI.
	panel_name: Name of the collapsible sub-panel that the property should be drawn in
	row_name: Properties with the same row_name will be drawn in the same row.
	entry_name: Name of the property to display in the UI, if not the same as the property name.
	info: The dictionary to store in the rig data.
	label_name: 
	"""

	assert ('prop_bone' in info) and ('prop_id' in info), f'Expected an info dict with at least "prop_bone" and "prop_id" keys. Instead got: {info}'

	if entry_name == "":
		entry_name = info['prop_id'].replace("_", " ").title()

	for key in info.keys():
		value = info[key]
		if type(value) in (list, dict):
			info[key] = json.dumps(value)

	# Read existing CloudRig UI data
	ui_data = {}
	if 'ui_data' in obj.data:
		ui_data = obj.data['ui_data'].to_dict()

	if panel_name not in ui_data:
		ui_data[panel_name] = {}
	if parent_id != "":
		ui_data[panel_name]['parent_id'] = parent_id

	if label_name not in ui_data[panel_name]:
		ui_data[panel_name][label_name] = {}
	if row_name not in ui_data[panel_name][label_name]:
		ui_data[panel_name][label_name][row_name] = {}
	if entry_name not in ui_data[panel_name][label_name][row_name]:
		ui_data[panel_name][label_name][row_name][entry_name] = {}

	prop_bone = info['prop_bone']
	if type(prop_bone) != str:
		info['prop_bone'] = prop_bone.name
	else:
		prop_bone = obj.pose.bones.get(prop_bone)
		assert prop_bone, "Properties bone doesn't exist: " + info['prop_bone']

	ui_data[panel_name][label_name][row_name][entry_name] = info

	# Update CloudRig UI data with the changes
	obj.data['ui_data'] = ui_data

	# Create custom property.
	prop_id = info['prop_id']
	if 'default' not in custom_prop_dict:
		custom_prop_dict['default'] = 0.0
	if type(prop_bone) == BoneInfo:
		prop_bone.custom_props[prop_id] = custom_prop_dict
	else:
		prop_bone[prop_id] = custom_prop_dict['default']
		prop_bone.id_properties_ui(prop_id).update(**custom_prop_dict)
		prop_bone.property_overridable_library_set(f'["{prop_id}"]', True)

class HiddenPrints:
	def __enter__(self):
		self._original_stdout = sys.stdout
		sys.stdout = open(os.devnull, 'w')

	def __exit__(self, exc_type, exc_val, exc_tb):
		sys.stdout.close()
		sys.stdout = self._original_stdout

def redraw_viewport():
	with HiddenPrints():
		bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)