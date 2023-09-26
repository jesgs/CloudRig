
from typing import Dict, Any
from bpy.types import Object

from ..utils.misc import get_addon_prefs
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
	def draw_prop(cls, context, layout, prop_owner, prop_name, **kwargs):
		is_forced = prop_name in cls.forced_params.keys()
		if is_forced and not cls.is_advanced_mode(context):
			return

		row = draw_prop(layout, prop_owner, prop_name, **kwargs)
		if is_forced:
			row.enabled = False

		return row

	@classmethod
	def draw_prop_search(cls, context, layout, prop_owner, prop_name, collection, coll_prop_name, **kwargs):
		rig = prop_owner.id_data

		is_forced = prop_name in cls.forced_params.keys()
		if is_forced and not cls.is_advanced_mode(context):
			return

		row = draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, **kwargs)

		if is_forced:
			row.enabled = False

		return row

def is_advanced_mode(context):
	if not is_cloud_metarig(context.object):
		return False
	return get_addon_prefs(context).advanced_mode

def is_cloud_metarig(rig: Object):
	if not rig.type == 'ARMATURE':
		return False
	return rig.data.cloudrig.enabled

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

def draw_prop(layout, prop_owner, prop_name, **kwargs):
	row = layout.row(align=True)
	row.prop(prop_owner, prop_name, **kwargs)
	return row

def draw_prop_search(layout, prop_owner, prop_name, collection, coll_prop_name, **kwargs):
	row = layout.row()
	row.prop_search(prop_owner, prop_name, collection, coll_prop_name, **kwargs)
	return row

def add_ui_data(obj
		,panel_name: str		# Name of the sub-panel that the property should be drawn in. These are created dynamically, so this can be anything.
		,row_name: str			# For drawing multiple properties in one row. TODO: Should be optional param?
		,info : Dict[str, Any]	# The dictionary to store in the rig data. See cloudrig.py -> draw_rig_settings()
		,entry_name = ""		# Name of the property to display in the UI. Defaults to the property name.
		,label_name = ""		# Allows organizing properties within sub-panels by labels.
		,parent_id = ""			# Allows creating nested sub-panels. TODO: Seems a bit wrong to have this here.
		,**custom_prop_dict		# Properties of the custom property to be created. TODO: In cloud_copy we want to call this function without re-creating the custom property.
	):
	"""Store a dict in the rig data, which is used by cloudrig.py to draw the CloudRig UI."""
	# TODO: This function is a bit convoluted because it accepts both BoneInfo and a str as the target bone,
	# and uses a PoseBone when it gets an str.
	# This is handy so that UI data and properties can be added both before and after generation,
	# but it might make more sense to make this two separate functions; Maybe one should be in
	# the BoneInfo class, and the other in rig_component_features/custom_props.

	# Also, it not only adds UI data but also creates the custom property.
	# Although this is handy because when adding UI data we also always want to create a property,
	# it would still make sense to split into two functions and just always call both of them.

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
	if type(prop_bone) == BoneInfo:
		info['prop_bone'] = prop_bone.name
	elif type(prop_bone) == str:
		prop_bone = obj.pose.bones.get(prop_bone)
		assert prop_bone, "Properties bone doesn't exist: " + info['prop_bone']

	ui_data[panel_name][label_name][row_name][entry_name] = info

	# Update CloudRig UI data with the changes
	obj.data['ui_data'] = ui_data

	# Create custom property.
	prop_id = info['prop_id']
	make_custom_property(prop_bone, prop_id, **custom_prop_dict)

def make_custom_property(prop_bone, prop_id, **kwargs):
	if 'default' not in kwargs:
		kwargs['default'] = 0.0
	if type(kwargs['default']) != bool:
		if 'min' not in kwargs:
			kwargs['min'] = 0
		if 'max' not in kwargs:
			kwargs['max'] = 1

	if type(prop_bone) == BoneInfo:
		# Let this function work for BoneInfo objects during the generation process.
		if 'overridable' not in kwargs:
			kwargs['overridable'] = True
		prop_bone.custom_props[prop_id] = kwargs
	else:
		if prop_id in prop_bone:
			# If the property already exists, don't update it.
			return
		prop_bone[prop_id] = kwargs['default']
		prop_bone.id_properties_ui(prop_id).update(**kwargs)
		prop_bone.property_overridable_library_set(f'["{prop_id}"]', True)

class HiddenPrints:
	def write(*args):
		# This is a workaround to /issues/83 based on 
		# https://stackoverflow.com/questions/6735917/redirecting-stdout-to-nothing-in-python
		pass

	def __enter__(self):
		self._original_stdout = sys.stdout
		try:
			sys.stdout = open(os.devnull, 'w')
		except FileNotFoundError:
			# Workaround, relies on this class having a write() method.
			sys.stdout = self

	def __exit__(self, exc_type, exc_val, exc_tb):
		sys.stdout.close()
		sys.stdout = self._original_stdout

def redraw_viewport():
	with HiddenPrints():
		bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
