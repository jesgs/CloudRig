import bpy
import os

def load_metarig(metarig_name):
	"""Append a metarig from MetaRigs.blend."""
	# Delete the metarig object Rigify just created for us in make_metarig_add_execute()
	bpy.ops.object.mode_set(mode='OBJECT')
	bpy.ops.object.delete(use_global=True)

	# Find an available name
	number = 1
	numbered_name = metarig_name
	while numbered_name in bpy.data.objects:
		numbered_name = metarig_name + "." + str(number).zfill(3)
		number += 1
	available_name = numbered_name

	# Loading metarig object from file
	filename = "metarigs/MetaRigs.blend"
	filedir = os.path.dirname(os.path.realpath(__file__))
	blend_path = os.path.join(filedir, filename)

	with bpy.data.libraries.load(blend_path) as (data_from, data_to):
		for o in data_from.objects:
			if o == metarig_name:
				data_to.objects.append(o)

	new_metarig = bpy.data.objects.get(available_name)
	if not new_metarig:
		print("Warning: Failed to load metarig: " + available_name)
		return

	bpy.context.scene.collection.objects.link(new_metarig)
	bpy.context.view_layer.objects.active = new_metarig
	new_metarig.location = bpy.context.scene.cursor.location

def load_sample(rig_name):
	"""Append a rig sample from MetaRigs.blend, then join it into the currently active armature."""

	sample_name = "Sample_"+rig_name

	rig = bpy.context.object
	bpy.ops.object.mode_set(mode='OBJECT')

	assert sample_name not in bpy.data.objects, "Error: Rig sample is floating around in the file, purge it!"

	# Loading rig sample object from file
	filename = "metarigs/MetaRigs.blend"
	filedir = os.path.dirname(os.path.realpath(__file__))
	blend_path = os.path.join(filedir, filename)

	with bpy.data.libraries.load(blend_path) as (data_from, data_to):
		for o in data_from.objects:
			if o == sample_name:
				data_to.objects.append(o)
	
	sample_ob = bpy.data.objects.get(sample_name)
	sample_ob.location = bpy.context.scene.cursor.location
	bpy.context.scene.collection.objects.link(sample_ob)
	bpy.ops.object.join()
	bpy.ops.object.mode_set(mode='EDIT')
