import bpy
from datetime import datetime as dt

blender_version = float(str(bpy.app.version[0]) + "." + str(bpy.app.version[1]) + str(bpy.app.version[2]))

date_format = "%Y-%m-%d"
build_date = dt.strptime(bpy.app.build_commit_date.decode(), date_format)

def is_before_register_commit():
	# https://developer.blender.org/rBAc20728941cf32e9cbe2f0bcd6ebae27bb6d01238
	register_commit_date = dt.strptime("2020-06-24", date_format)
	return build_date < register_commit_date

def do_blender_versioning():
	"""Code that needs to run only for specific versions of Blender."""
	pass

def version_cloud_metarig(metarig):
	"""Convert older CloudRig metarigs to work with the current version of the addon as well as possible."""

	# Beginning of metarig versioning: 2020-30-06. 
	# I should've started this sooner. Metarigs older than this are not guaranteed backwards compatibility.
	if metarig.cloudrig_parameters.version == 0.0:
		metarig.cloudrig_parameters.version = 0.1
		# TODO: Assume that version 0.0 is the metarigs in CoffeeRun crowd.blend, and try to make them work with current CloudRig.
	pass

def version_all_cloud_metarigs():
	cloud_metarigs = [o for o in bpy.data.objects if o.type=='ARMATURE' and is_cloud_metarig(o)]
	for metarig in cloud_metarigs:
		version_cloud_metarig(metarig)