# Data Container and utilities for de-coupling bone creation and setup from BPY.
# Lets us easily create bones without having to worry about edit/pose mode.
import bpy
from .id import ID
from mathutils import Vector
import copy
from ..rigs import cloud_utils
from rigify.utils.mechanism import make_constraint, make_driver

class BoneInfoContainer(ID):
	# TODO: implement __iter__ and such.
	def __init__(self, cloudrig):
		self.bones = []
		self.cloudrig = cloudrig
		self.armature = cloudrig.obj
		self.defaults = cloudrig.defaults	# For overriding arbitrary properties' default values when creating bones in this container.
		self.scale = cloudrig.scale

	def find(self, name):
		"""Find a BoneInfo instance by name, return it if found."""
		for bd in self.bones:
			if(bd.name == name):
				return bd
		return None

	def bone(self, name="Bone", source=None, overwrite=True, bone_group=None, **kwargs):
		"""Define a bone and add it to the list of bones. If it already exists, return or re-define it depending on overwrite param."""

		bi = self.find(name)
		if bi and not overwrite: 
			return bi
		elif bi:
			self.bones.remove(bi)

		bi = BoneInfo(self, name, source, bone_group, **kwargs)
		self.bones.append(bi)
		return bi
	
	def from_edit_bone(self, armature, edit_bone):
		"""Create a BoneInfo instance based on an existing Blender bone, and add it to this container."""
		# NOTE: This is currently not used.
		eb = edit_bone
		pose_bone = armature.pose.bones.get(eb.name)
		assert pose_bone, f"Error: Failed to create BoneInfo from EditBone {eb.name} because corresponding PoseBone does not exist. Make sure to leave Edit Mode after creating a bone to make sure it's fully initialized."
		
		bi = self.bone(eb.name)

		### Edit Bone properties
		bi.parent = eb.parent.name if eb.parent else ""
		bi.head = eb.head.copy()
		bi.tail = eb.tail.copy()
		bi.roll = eb.roll

		bi.bbone_curveinx = eb.bbone_curveinx
		bi.bbone_curveiny = eb.bbone_curveiny
		bi.bbone_curveoutx = eb.bbone_curveoutx
		bi.bbone_curveouty = eb.bbone_curveouty
		bi.bbone_easein = eb.bbone_easein
		bi.bbone_easeout = eb.bbone_easeout
		bi.bbone_scaleinx = eb.bbone_scaleinx
		bi.bbone_scaleiny = eb.bbone_scaleiny
		bi.bbone_scaleoutx = eb.bbone_scaleoutx
		bi.bbone_scaleouty = eb.bbone_scaleouty

		### Pose Bone Properties
		pb = pose_bone
		bi.bone_group = self.container.cloudrig.generator.bone_groups.find(eb.bone_group.name)
		if pb.custom_shape:
			bi.custom_shape = pb.custom_shape
		if pb.custom_shape_transform:
			bi.custom_shape_transform = self.find(pb.custom_shape_transform.name)
		bi.custom_shape_scale = pb.custom_shape_scale
		bi.use_custom_shape_bone_size = pb.use_custom_shape_bone_size

		bi.lock_location = pb.lock_location
		bi.lock_rotation = pb.lock_rotation
		bi.lock_rotation_w = pb.lock_rotation_w
		bi.lock_scale = pb.lock_scale

		### Bone properties
		b = pb.bone
		bi.name = b.name
		bi.layers = b.layers[:]
		bi.rotation_mode = b.rotation_mode
		bi.hide_select = b.hide_select
		bi.hide = b.hide

		bi.use_connect = b.use_connect
		bi.use_deform = b.use_deform
		bi.show_wire = b.show_wire
		bi.use_endroll_as_inroll = b.use_endroll_as_inroll

		bi._bbone_x = b.bbone_x
		bi._bbone_z = b.bbone_z
		bi.bbone_segments = b.bbone_segments
		bi.bbone_handle_type_start = b.bbone_handle_type_start
		bi.bbone_handle_type_end = b.bbone_handle_type_end

		if b.bbone_custom_handle_start:
			bi.bbone_custom_handle_start = b.bbone_custom_handle_start.name
		if b.bbone_custom_handle_end:
			bi.bbone_custom_handle_end = b.bbone_custom_handle_end.name

		bi.envelope_distance = b.envelope_distance
		bi.envelope_weight = b.envelope_weight
		bi.use_envelope_multiply = b.use_envelope_multiply
		bi.head_radius = b.head_radius
		bi.tail_radius = b.tail_radius

		bi.use_inherit_rotation = b.use_inherit_rotation
		bi.inherit_scale = b.inherit_scale
		bi.use_local_location = b.use_local_location
		bi.use_relative_parent = b.use_relative_parent

		# Read Constraint data
		skip = ['name', 'constraints', 'bl_rna', 'type', 'rna_type', 'error_location', 'error_rotation', 'is_proxy_local', 'is_valid', 'children']
		for c in pose_bone.constraints:
			constraint_data = (c.type, {})
			for attr in dir(c):
				if "__" in attr: continue
				if attr in skip: continue
				constraint_data[1][attr] = getattr(c, attr)

			bi.constraints.append(constraint_data)
		
		return bi

	def clone_bone_info(self, bone_info, new_name=None):
		"""Create a clone of a bone_info, add it to our list and return it."""
		my_clone = bone_info.clone(new_name=new_name)
		self.bones.append(my_clone)
		return my_clone

	def clear(self):
		self.bones = []

class BoneInfo(ID):
	""" 
	The purpose of this class is to abstract bpy.types.Bone, bpy.types.PoseBone and bpy.types.EditBone
	into a single concept.

	This class does not concern itself with posing the bone, only creating and rigging it.
	Eg, it does not store pose bone transformations such as loc/rot/scale. 
	"""

	def __init__(self, container, name="Bone", source=None, bone_group=None, **kwargs):
		""" 
		container: Need a reference to what BoneInfoContainer this BoneInfo belongs to.
		source:	Bone to take transforms from (head, tail, roll, bbone_x, bbone_z).
		kwargs: Allow setting arbitrary bone properties at initialization.
		"""

		self.container = container

		### The following dictionaries store pure information, never references to the real thing. ###
		# PoseBone custom properties.
		self.custom_props = {}
		# EditBone custom properties.
		self.custom_props_edit = {}
		# data_path:Driver dictionary, where data_path is from the bone. Only for drivers that are directly on a bone property! Not a sub-ID like constraints.
		self.new_style_drivers = []	# Rigify make_driver() compliant driver storage.
		self.drivers = {}
		self.bone_drivers = {}

		# List of ConstraintInfo objects.
		self.constraint_infos = []

		### Edit Bone properties
		self.parent = None	# Blender expects bpy.types.EditBone, but we store definitions.bone.BoneInfo. str is also supported for now, but should be avoided.
		self.head = Vector((0,0,0))
		self.tail = Vector((0,1,0))
		self.roll = 0
		# NOTE: For these bbone properties, we are referring only to edit bone versions of the values.
		self.bbone_curveinx = 0
		self.bbone_curveiny = 0
		self.bbone_curveoutx = 0
		self.bbone_curveouty = 0
		self.bbone_easein = 1
		self.bbone_easeout = 1
		self.bbone_scaleinx = 1
		self.bbone_scaleiny = 1
		self.bbone_scaleoutx = 1
		self.bbone_scaleouty = 1

		### Bone properties
		self.name = name
		self.layers = [l==0 for l in range(32)]	# 32 bools where only the first one is True.
		self.rotation_mode = 'QUATERNION'
		self.hide_select = False
		self.hide = False

		self.use_connect = False
		self.use_deform = False
		self.show_wire = False
		self.use_endroll_as_inroll = False

		self._bbone_x = 0.1		# NOTE: These two are wrapped by bbone_width @property.
		self._bbone_z = 0.1
		self.bbone_segments = 1
		self.bbone_handle_type_start = "AUTO"
		self.bbone_handle_type_end = "AUTO"
		self.bbone_custom_handle_start = ""	# Blender expects bpy.types.Bone, but we store str.	TODO: We should store BoneInfo here as well!!
		self.bbone_custom_handle_end = ""	# Blender expects bpy.types.Bone, but we store str.

		self.envelope_distance = 0.25
		self.envelope_weight = 1.0
		self.use_envelope_multiply = False
		self.head_radius = 0.1
		self.tail_radius = 0.1

		self.use_inherit_rotation = True
		self.inherit_scale = "FULL"
		self.use_local_location = True
		self.use_relative_parent = False

		### Pose Mode Only
		self._bone_group = None		# Blender expects bpy.types.BoneGroup, we store definitions.bone_group.BoneGroup. It is also wrapped by bone_group @property.
		self.custom_shape = None	# Blender expects bpy.types.Object, we store bpy.types.Object.
		self.custom_shape_transform = None	# Blender expects bpy.types.PoseBone, we store definitions.bone.BoneInfo.
		self.custom_shape_scale = 1.0
		self.use_custom_shape_bone_size = False

		self.lock_location = [False, False, False]
		self.lock_rotation = [False, False, False]
		self.lock_rotation_w = False
		self.lock_scale = [False, False, False]

		# Apply container's defaults
		for key, value in self.container.defaults.items():
			setattr(self, key, value)

		if source:
			self.head = source.head.copy()
			self.tail = source.tail.copy()
			self.roll = source.roll
			self.envelope_distance = source.envelope_distance
			self.envelope_weight = source.envelope_weight
			self.use_envelope_multiply = source.use_envelope_multiply
			self.head_radius = source.head_radius
			self.tail_radius = source.tail_radius
			if type(source)==BoneInfo:
				self._bone_group = source._bone_group
				self.bbone_width = source.bbone_width
			else:
				self._bbone_x = source.bbone_x
				self._bbone_z = source.bbone_z
			if source.parent:
				if type(source)==bpy.types.EditBone:
					self.parent = source.parent.name
				else:
					self.parent = source.parent 

		if type(bone_group) != str:
			self.bone_group = bone_group

		# Apply property values from arbitrary keyword arguments if any were passed.
		for key, value in kwargs.items():
			setattr(self, key, value)

	def clone(self, new_name=None):
		"""Return a clone of self."""
		custom_ob_backup = self.custom_object	# This would fail to deepcopy since it's a bpy.types.Object.
		self.custom_object = None

		my_clone = copy.deepcopy(self)
		my_clone.name = self.name + ".001"
		if new_name:
			my_clone.name = new_name

		my_clone.custom_object = custom_ob_backup

		return my_clone

	def __str__(self):
		return self.name

	@property
	def bbone_width(self):
		return self._bbone_x / self.container.scale

	@bbone_width.setter
	def bbone_width(self, value):
		"""Set BBone width relative to the rig's scale."""
		self._bbone_x = value * self.container.scale
		self._bbone_z = value * self.container.scale
		self.envelope_distance = value * self.container.scale
		self.head_radius = value * self.container.scale
		self.tail_radius = value * self.container.scale

	@property
	def bone_group(self):
		return self._bone_group

	@bone_group.setter
	def bone_group(self, bg):
		# bg is expected to be a cloudrig.definitions.bone_group.Bone_Group object.
		# Bone Group assignment is handled directly by the Bone Group object.
		if bg:
			bg.assign_bone(self)
		elif self._bone_group:
			self._bone_group.remove_bone(self)

	@property
	def vec(self):
		"""Vector pointing from head to tail."""
		return self.tail-self.head

	@vec.setter
	def vec(self, value):
		self.tail = self.head + value

	def scale_width(self, value):
		"""Set bbone width relative to current."""
		self.bbone_width *= value

	def scale_length(self, value):
		"""Set bone length relative to its current length."""
		self.tail = self.head + self.vec * value

	@property
	def length(self):
		return (self.tail-self.head).length

	@length.setter
	def length(self, value):
		assert value > 0, "Length cannot be 0!"
		self.tail = self.head + self.vec.normalized() * value

	@property
	def center(self):
		return self.head + self.vec/2

	def set_layers(self, layerlist, additive=False):
		cloud_utils.set_layers(self, layerlist, additive)

	def put(self, loc, length=None, width=None, scale_length=None, scale_width=None):
		offset = loc-self.head
		self.head = loc
		self.tail = loc+offset

		if length:
			self.length=length
		if width:
			self.bbone_width = width
		if scale_length:
			self.scale_length(scale_length)
		if scale_width:
			self.scale_width(scale_width)

	def flatten(self):
		self.vec = cloud_utils.flat(self.vec)
		from math import pi
		deg = self.roll*180/pi
		# Round to nearest 90 degrees.
		rounded = round(deg/90)*90
		self.roll = pi/180*rounded

	def disown(self, new_parent):
		""" Parent all children of this bone to a new parent. """
		for b in self.container.bones:
			if b.parent==self or b.parent==self.name:
				b.parent = new_parent

	def get_constraint(self, name):
		for ci in self.constraint_infos:
			if ci.name == name:
				return ci

	def add_constraint(self, armature, contype, index=None, **kwargs):
		"""Store constraint information about a constraint in this BoneInfo.
		contype: Type of constraint, eg. 'STRETCH_TO'.
		kwargs: Dictionary of properties and values.
		true_defaults: When False, we use a set of arbitrary default values that I consider better than Blender's defaults.
		"""

		con_info = ConstraintInfo(self, contype, **kwargs)
		if index:
			self.constraint_infos.insert(index, con_info)
		else:
			self.constraint_infos.append(con_info)

		return con_info

	def clear_constraints(self):
		self.constraint_infos = []

	def write_edit_data(self, armature, edit_bone):
		"""Write relevant data into an EditBone."""
		assert armature.mode == 'EDIT', "Error: Armature must be in Edit Mode when writing edit bone data."

		# Check for 0-length bones.
		if (self.head - self.tail).length == 0:
			# Warn and force length.
			print("WARNING: Had to force 0-length bone to have some length: " + self.name)
			self.tail = self.head+Vector((0, 0.1, 0))

		### Edit Bone properties
		eb = edit_bone
		eb.use_connect = False	# NOTE: Without this, ORG- bones' Copy Transforms constraints can't work properly.

		if self.parent:
			if type(self.parent)==str:
				eb.parent = armature.data.edit_bones.get(self.parent)
			else:
				eb.parent = armature.data.edit_bones.get(self.parent.name)

		eb.head = self.head.copy()
		eb.tail = self.tail.copy()
		eb.roll = self.roll

		eb.bbone_curveinx = self.bbone_curveinx
		eb.bbone_curveiny = self.bbone_curveiny
		eb.bbone_curveoutx = self.bbone_curveoutx
		eb.bbone_curveouty = self.bbone_curveouty
		eb.bbone_easein = self.bbone_easein
		eb.bbone_easeout = self.bbone_easeout
		eb.bbone_scaleinx = self.bbone_scaleinx
		eb.bbone_scaleiny = self.bbone_scaleiny
		eb.bbone_scaleoutx = self.bbone_scaleoutx
		eb.bbone_scaleouty = self.bbone_scaleouty

		# Custom Properties.
		for key, prop in self.custom_props_edit.items():
			prop.make_real(edit_bone)

	def write_pose_data(self, pose_bone):
		"""Write relevant data into a PoseBone."""
		armature = pose_bone.id_data

		assert armature.mode != 'EDIT', "Armature cannot be in Edit Mode when writing pose data"
		
		# Pose bone data
		pb = pose_bone
		pb.custom_shape = self.custom_shape
		pb.custom_shape_scale = self.custom_shape_scale
		if self.custom_shape_transform:
			pb.custom_shape_transform = armature.pose.bones.get(self.custom_shape_transform.name)
		pb.use_custom_shape_bone_size = self.use_custom_shape_bone_size

		pb.lock_location = self.lock_location
		pb.lock_rotation = self.lock_rotation
		pb.lock_rotation_w = self.lock_rotation_w
		pb.lock_scale = self.lock_scale

		pb.rotation_mode = self.rotation_mode

		# Bone data
		b = pb.bone
		b.layers = self.layers[:]
		b.use_deform = self.use_deform
		b.bbone_x = self._bbone_x
		b.bbone_z = self._bbone_z
		b.bbone_segments = self.bbone_segments
		b.bbone_handle_type_start = self.bbone_handle_type_start
		b.bbone_handle_type_end = self.bbone_handle_type_end
		b.bbone_custom_handle_start = armature.data.bones.get(self.bbone_custom_handle_start or "")
		b.bbone_custom_handle_end = armature.data.bones.get(self.bbone_custom_handle_end or "")
		b.show_wire = self.show_wire
		b.use_endroll_as_inroll = self.use_endroll_as_inroll
		
		b.hide_select = self.hide_select
		b.hide = self.hide

		b.use_inherit_rotation = self.use_inherit_rotation
		b.inherit_scale = self.inherit_scale
		b.use_local_location = self.use_local_location
		b.use_relative_parent = self.use_relative_parent

		b.envelope_distance = self.envelope_distance
		b.envelope_weight = self.envelope_weight
		b.use_envelope_multiply = self.use_envelope_multiply
		b.head_radius = self.head_radius
		b.tail_radius = self.tail_radius
		
		# Constraints.
		for ci in self.constraint_infos:
			con = ci.make_real(pb)
			for driver_info in ci.drivers:
				driver_info['prop'] = f'pose.bones["{pb.name}"].constraints["{con.name}"].{driver_info["prop"]}'
				self.container.cloudrig.make_driver(self.container.cloudrig.obj, **driver_info)
		
		# Custom Properties.
		for key, prop in self.custom_props.items():
			prop.make_real(pose_bone)
		
		# Pose Bone Property Drivers.
		for path, d in self.drivers.items():
			data_path = f'pose.bones["{pose_bone.name}"].{path}'
			d.make_real(pose_bone.id_data, data_path)
		
		# New style drivers.
		for driver_info in self.new_style_drivers:
			data_path = driver_info['prop']
			
			try:
				driver_info['prop'] = f'pose.bones["{pb.name}"].{data_path}'
				self.container.cloudrig.make_driver(self.container.cloudrig.obj, **driver_info)
			except TypeError:
				# If we couldn't add the driver to the pose bone, try the data bone.
				driver_info['prop'] = f'bones["{pb.name}"].{data_path}'
				self.container.cloudrig.make_driver(self.container.cloudrig.obj.data, **driver_info)
	
		# Data Bone Property Drivers.
		for path, d in self.bone_drivers.items():
			#HACK: If we want to add drivers to bone properties that are shared between pose and edit mode, they aren't stored under armature.pose.bones[0].property but instead armature.bones[0].property... The entire way we handle drivers should be scrapped tbh. :P
			# But scrapping that requires scrapping the way we handle bones, so... just keep making it work.
			data_path = f'bones["{pose_bone.name}"].{path}'
			d.make_real(pose_bone.id_data.data, data_path)
	
	def get_real(self, armature):
		"""If a bone with the name in this BoneInfo exists in the passed armature, return it."""
		if armature.mode == 'EDIT':
			return armature.data.edit_bones.get(self.name)
		else:
			return armature.pose.bones.get(self.name)

class ConstraintInfo:
	"""Helper class to store and manage constraint info before it's passed to Rigify's make_constraint."""

	def __init__(self, bone_info, con_type, target=None, preferred_defaults=True, **kwargs):
		self.type = con_type
		self.bone_info = bone_info	# BoneInfo to which this constraint is being added.
		self.target = target
		self.name = self.type.replace("_", " ").title()
		self.drivers = []
		
		for key, value in kwargs.items():
			self.__dict__[key] = value

		if preferred_defaults:
			self.set_preferred_defaults()

	def set_preferred_defaults(self):
		"""Set some arbitrary preferred defaults, separately from __init__(), to keep this optional."""

		self.target = self.bone_info.container.armature

		# Constraints that support local space should default to local space.
		support_local = ['COPY_LOCATION', 'COPY_SCALE', 'COPY_ROTATION', 'COPY_TRANSFORMS',
						'LIMIT_LOCATION', 'LIMIT_SCALE', 'LIMIT_ROTATION',
						'ACTION', 'TRANSFORM']
		if not hasattr(self, 'space') and self.type in support_local:
			self.space = 'LOCAL'
		if self.type == 'STRETCH_TO':
			self.use_bulge_min = True
			self.use_bulge_max = True
		elif self.type in ['COPY_LOCATION', 'COPY_SCALE']:
			self.use_offset = self.space != 'WORLD'
		elif self.type == 'COPY_ROTATION':
			if self.space != 'WORLD':
				self.mix_mode = 'BEFORE'
				self.use_offset = True
		elif self.type in ['COPY_TRANSFORMS', 'ACTION']:
			if self.space != 'WORLD':
				self.mix_mode = 'BEFORE'
		elif self.type == 'LIMIT_SCALE':
			self.max_x = 1
			self.max_y = 1
			self.max_z = 1
			self.use_transform_limit = True
		elif self.type in ['LIMIT_LOCATION', 'LIMIT_ROTATION']:
			self.use_transform_limit = True
		elif self.type == 'IK':
			self.chain_count = 2
			self.pole_target = self.target
	
	def make_real(self, pose_bone):
		con_type = self.type
		con_info = self.__dict__.copy()
		for key in ['type', 'bone_info', 'drivers']:
			del con_info[key]

		targets = None
		if con_type == 'ARMATURE' and 'targets' in con_info:
			print(con_info)
			targets = con_info['targets']
			del con_info['targets']
			del con_info['target']

		con = make_constraint(pose_bone, con_type, **con_info)
		
		if con_type == 'ARMATURE' and targets:
			for target_info in targets:
				target = con.targets.new()
				target.target = pose_bone.id_data
				for prop in ['weight', 'target', 'subtarget']:
					if prop in target_info:
						setattr(target, prop, target_info[prop])
			
		# Fix stretch constraints
		if con_type == 'STRETCH_TO':
			con.rest_length = 0
		
		return con