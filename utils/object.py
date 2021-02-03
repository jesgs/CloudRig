import bpy

class EnsureVisible:
	"""Ensure an object is visible, then reset it to how it was before."""

	def __init__(self, obj):
		""" Ensure an object is visible, and create this small object to manage that object's visibility-ensured-ness. """
		self.obj_name = obj.name
		self.obj_hide = obj.hide_get()
		self.obj_hide_viewport = obj.hide_viewport
		self.temp_coll = None

		space = bpy.context.area.spaces.active
		if hasattr(space, 'local_view') and space.local_view:
			bpy.ops.view3d.localview()

		if not obj.visible_get():
			obj.hide_set(False)
			obj.hide_viewport = False

		if not obj.visible_get():
			# If the object is still not visible, we need to move it to a visible collection. To not break other scripts though, we should restore the active collection afterwards.
			active_coll = bpy.context.collection

			coll_name = "temp_visible"
			temp_coll = bpy.data.collections.get(coll_name)
			if not temp_coll:
				temp_coll = bpy.data.collections.new(coll_name)
			if coll_name not in bpy.context.scene.collection.children:
				bpy.context.scene.collection.children.link(temp_coll)

			if obj.name not in temp_coll.objects:
				temp_coll.objects.link(obj)

			self.temp_coll = temp_coll

			set_active_collection(active_coll)

	def restore(self):
		"""Restore visibility settings to their original state."""
		obj = bpy.data.objects.get(self.obj_name)
		if not obj: return

		obj.hide_set(self.obj_hide)
		obj.hide_viewport = self.obj_hide_viewport

		# Remove object from temp collection
		if self.temp_coll and obj.name in self.temp_coll.objects:
			self.temp_coll.objects.unlink(obj)

			# Delete temp collection if it's empty now.
			if len(self.temp_coll.objects) == 0:
				bpy.data.collections.remove(self.temp_coll)
				self.temp_coll = None

class CloudObjectUtilitiesMixin:
	@staticmethod
	def set_layers(obj, layerlist, additive=False):
		return set_layers(obj, layerlist, additive)

	@staticmethod
	def lock_transforms(obj, loc=True, rot=True, scale=True):
		return lock_transforms(obj, loc, rot, scale)

	@staticmethod
	def ensure_visible(obj) -> EnsureVisible:
		return EnsureVisible(obj)

	def add_to_widget_collection(self, obj):
		self.generator.add_to_widget_collection(obj)

def lock_transforms(obj, loc=True, rot=True, scale=True):
	if type(loc) in (list, tuple):
		obj.lock_location = loc
	else:
		obj.lock_location = [loc, loc, loc]

	if type(rot) in (list, tuple):
		obj.lock_rotation = rot[:3]
		if len(rot)==4:
			obj.lock_rotation_w = rot[-1]
	else:
		obj.lock_rotation = [rot, rot, rot]
		obj.lock_rotation_w = rot

	if type(scale) in (list, tuple):
		obj.lock_scale = scale
	else:
		obj.lock_scale = [scale, scale, scale]

def set_layers(obj, layerlist, additive=False):
	"""Layer setting function that can take either a list of booleans or a list of ints.
	In case of booleans, it must be a 32 length list, and we set the bone's layer list to the passed list.
	In case of ints, enable the layers with the indicies in the passed list.

	obj can either be a bone or an armature.
	"""
	layers = list(obj.layers[:])
	layerlist = layerlist[:]

	if not additive:
		layers = [False]*32
	for i, e in enumerate(layerlist):
		if type(e)==bool:
			assert len(layerlist)==32, f"Layer assignment expected a list of 32 booleans, got {len(layerlist)}."
			layers[i] = e or layers[i]
		elif type(e)==int:
			layers[e] = True

	obj.layers = layers[:]

def recursive_search_layer_collection(collName, layerColl=None) -> bpy.types.LayerCollection:
	# Recursivly transverse layer_collection for a particular name
	# This is the only way to set active collection as of 14-04-2020.
	if not layerColl:
		layerColl = bpy.context.view_layer.layer_collection

	found = None
	if (layerColl.name == collName):
		return layerColl
	for layer in layerColl.children:
		found = recursive_search_layer_collection(collName, layer)
		if found:
			return found

def set_active_collection(collection):
	layer_collection = recursive_search_layer_collection(collection.name)
	bpy.context.view_layer.active_layer_collection = layer_collection
