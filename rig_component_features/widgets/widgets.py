from typing import List
from rigify.base_rig import BaseRig
from ...rig_component_features.bone import BoneInfo

import bpy
from mathutils import Vector
from ...utils.maths import project_points_on_plane, scale_points_from_center
import os

def assign_to_collection(obj, collection):
	if obj.name not in collection.objects:
		collection.objects.link(obj)

def get_widget_blend_path() -> str:
	filename = "Widgets.blend"
	filedir = os.path.dirname(os.path.realpath(__file__))
	blend_path = os.path.join(filedir, filename)
	return blend_path

def ensure_widget(wgt_name, overwrite=True, collection=None, clear_asset=True):
	""" Load custom shapes by appending them from Widgets.blend, unless they already exist in this file. """

	if not collection:
		collection = bpy.context.scene.collection

	# Check if it already exists locally.
	if not wgt_name.startswith("WGT-"):
		wgt_name = "WGT-"+wgt_name
	wgt_ob = bpy.data.objects.get((wgt_name, None))

	if wgt_ob:
		assign_to_collection(wgt_ob, collection)
		if overwrite:
			# If it exists, and we want to update it, rename it while we append the new one.
			wgt_ob.name = wgt_ob.name + "_temp"
			wgt_ob.data.name = wgt_ob.data.name + "_temp"
		else:
			return wgt_ob

	# Loading widget object from file.
	blend_path = get_widget_blend_path()

	with bpy.data.libraries.load(blend_path) as (data_from, data_to):
		for o in data_from.objects:
			if o == wgt_name:
				data_to.objects.append(o)

	new_wgt_ob = bpy.data.objects.get((wgt_name, None))
	if not new_wgt_ob:
		# Widget name was not in resource file, so nothing to overwrite with.
		# Just clear the _temp from the end of the names.
		wgt_ob.name = wgt_name
		wgt_ob.data.name = wgt_name
		return wgt_ob
	elif wgt_ob:
		# Update original object with new one's data, then delete new object.
		old_data_name = wgt_ob.data.name
		wgt_ob.data = new_wgt_ob.data
		wgt_ob.name = wgt_name
		bpy.data.meshes.remove(bpy.data.meshes.get(old_data_name))
		bpy.data.objects.remove(new_wgt_ob)
	else:
		wgt_ob = new_wgt_ob

	if clear_asset:
		wgt_ob.asset_clear()
	assign_to_collection(wgt_ob, collection)

	return wgt_ob
