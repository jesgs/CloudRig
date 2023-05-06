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


def bezier_widget(rig: BaseRig, coords: List[Vector], bone: BoneInfo, scale=1.3):
	"""UNUSED. This works poorly when two eye bones are facing upwards."""
	"""Create a bezier curve widget where coords is a list of Vectors that the curve should be near."""

	# If the object already exists and we aren't forcing a widget update, return existing.
	ob_name = "WGT-" + bone.name
	existing = bpy.data.objects.get((ob_name, None))
	if existing:
		if not rig.generator.metarig.data.rigify_force_widget_update:
			return existing
		else:
			# If the object exists locally, delete it.
			bpy.data.objects.remove(existing)

	context = bpy.context
	bpy.ops.object.mode_set(mode='OBJECT')
	curve = bpy.data.curves.new(ob_name, 'CURVE')
	curve.dimensions = '3D'
	obj = bpy.data.objects.new(ob_name, curve)

	spline = curve.splines.new('BEZIER')
	spline.use_cyclic_u = True

	context.scene.collection.objects.link(obj)

	if len(coords)<3:
		# If there are less than 3 coordinates, make some more.
		new_coords = []
		shift = Vector((0, 0, 0.1))
		for co in coords:
			co.xyz = co-shift
			new_coords.append(co+shift)
		coords.extend(new_coords)

	# Flatten the points.
	coords = project_points_on_plane(coords, bone.vector)

	# Expand the points
	coords = scale_points_from_center(coords, scale)

	# Create and place the spline points.
	spline.bezier_points.add(len(coords)-1)
	for i, p in enumerate(spline.bezier_points):
		co = coords[i]
		# world->bone axis shuffle...
		p.co[0] = co[0]
		p.co[1] = co[2]
		p.co[2] = -co[1]
		p.handle_left_type = 'AUTO'
		p.handle_right_type = 'AUTO'

	# Convert to mesh.
	bpy.ops.object.select_all(action='DESELECT')
	context.view_layer.objects.active = obj
	obj.select_set(True)
	bpy.ops.object.convert(target='MESH')

	# Assign to widget collection.
	obj.data.name = obj.name
	context.scene.collection.objects.unlink(obj)
	assign_to_collection(obj, rig.generator.widget_collection)

	# Restore selection and mode.
	context.view_layer.objects.active = rig.obj
	rig.obj.select_set(True)
	bpy.ops.object.mode_set(mode='EDIT')

	return obj