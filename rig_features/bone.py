from typing import List, Tuple
from bpy.types import EditBone, PoseBone, Constraint, Context, Object

from mathutils import Vector, Matrix

from ..utils.maths import flat
from ..rig_features.object import set_layers
from rigify.utils.mechanism import make_constraint, make_driver, make_property

# These values should match Blender's defaults, otherwise they won't be written.
edit_bone_properties = {
	'head' : Vector((0, 0, 0))
	,'tail' : Vector((0, 1, 0))
	,'roll' : 0
	,'head_radius' : 0.1
	,'tail_radius' : 0.05
	,'use_connect' : False

	,'bbone_curveinx' : 0
	,'bbone_curveinz' : 0
	,'bbone_curveoutx' : 0
	,'bbone_curveoutz' : 0
	,'bbone_easein' : 1
	,'bbone_easeout' : 1
	,'bbone_scalein' : Vector((1, 1, 1))
	,'bbone_scaleout' : Vector((1, 1, 1))

	# These axis values are only read for original bones. Updating them after 
	# changing roll or head/tail positions would require some serious maths
	# or some functions to be exposed from C.
	,'x_axis' : Vector()
	,'y_axis' : Vector()
	,'z_axis' : Vector()
}

bone_properties = {
	'layers' : [l==0 for l in range(32)]	# 32 bools where only the first one is True.
	,'hide_select' : False
	,'hide' : False

	,'use_deform' : False
	,'show_wire' : False
	,'use_endroll_as_inroll' : False

	,'bbone_x' : 0.1		# NOTE: These two are wrapped by bbone_width @property.
	,'bbone_z' : 0.1
	,'bbone_segments' : 1
	,'bbone_handle_type_start' : 'AUTO'
	,'bbone_handle_type_end' : 'AUTO'
	,'bbone_custom_handle_start': None	# BoneInfo
	,'bbone_custom_handle_end': None	# BoneInfo
	,'bbone_handle_use_scale_start': [False, False, False]
	,'bbone_handle_use_scale_end': [False, False, False]
	,'bbone_handle_use_ease_start': False
	,'bbone_handle_use_ease_end': False

	,'envelope_distance' : 0.25
	,'envelope_weight' : 1.0
	,'use_envelope_multiply' : False
	,'head_radius' : 0.1
	,'tail_radius' : 0.1

	,'use_inherit_rotation' : True
	,'inherit_scale' : 'FULL'
	,'use_local_location' : True
	,'use_relative_parent' : False
}

pose_bone_properties = {
	'bone_group' : ""		# This should be str, NOT a bpy.types.BoneGroup!

	,'custom_shape' : None	# bpy.types.Object
	,'custom_shape_transform' : None # BoneInfo
	,'custom_shape_scale_xyz' : Vector((1.0, 1.0, 1.0))
	,'custom_shape_translation' : Vector((0.0, 0.0, 0.0))
	,'custom_shape_rotation_euler' : Vector((0.0, 0.0, 0.0))
	,'use_custom_shape_bone_size' : True

	,'rotation_mode' : 'QUATERNION'
	,'lock_location' : [False, False, False]
	,'lock_rotation' : [False, False, False]
	,'lock_rotation_w' : False
	,'lock_scale' : [False, False, False]

	,'ik_stretch' : 0
	,'lock_ik_x' : False
	,'lock_ik_y' : False
	,'lock_ik_z' : False
	,'ik_stiffness_x' : 0
	,'ik_stiffness_y' : 0
	,'ik_stiffness_z' : 0
	,'use_ik_limit_x' : False
	,'use_ik_limit_y' : False
	,'use_ik_limit_z' : False
	,'ik_min_x' : 0
	,'ik_max_x' : 0
	,'ik_min_y' : 0
	,'ik_max_y' : 0
	,'ik_min_z' : 0
	,'ik_max_z' : 0
}

class BoneInfo:
	"""
	The purpose of this class is to abstract bpy.types.Bone, bpy.types.PoseBone
	and bpy.types.EditBone into a single concept.

	This class does not concern itself with posing the bone, only creating and
	rigging it. Eg, it does not store transformations such as loc/rot/scale.
	"""

	def init_variables(self, var_dict):
		for key in var_dict.keys():
			value = var_dict[key]
			if type(value) in [Vector, Matrix]:
				value = value.copy()
			setattr(self, key, value)

	def __init__(self, bone_set, name="Bone", source: EditBone or BoneInfo = None, **kwargs):
		"""
		source:	Bone to take transforms from (head, tail, roll, bbone_x, bbone_z).
		kwargs: Allow setting arbitrary bone properties at initialization.
		"""

		self.bone_set = bone_set
		self.owner_rig = None			# This should be set after creating the instance!
		self.next = self.prev = None	# For LinkedList behaviour.
		self.gizmo_vgroup = ""			# For CloudRig Gizmos
		self.gizmo_operator = 'transform.translate'

		self.custom_props = {}			# {"name" : {kwargs}} where kwargs will be passed to Rigify's make_property().
		self.custom_props_edit = {}
		self.drivers = []				# List of dictionaries that will be passed to Rigify's make_driver().
		self.drivers_data = []			# Same but for data bone properties.

		self.constraint_infos = []		# List of ConstraintInfo objects. Their __dict__ will be passed to Rigify's make_constraint().

		self._name = name
		self._parent = None
		self.children: List[BoneInfo] = []

		self.init_variables(edit_bone_properties)
		self.init_variables(bone_properties)
		self.init_variables(pose_bone_properties)
		self.use_custom_shape_bone_size = False		# A better default.
		self.use_custom_shape_bbone_scaling = True	# Custom boolean for CloudRig, used by the generator.

		# Recalculate Roll
		# TODO: Refactor this so that roll_type is gone, and just the existence of roll_bone or roll_vector indicates what should be done.
		self.roll_type = ""				# Whether the roll_bone or roll_vector should be used to calculate bone roll..
		self.roll_bone = None			# If roll_type=='ALIGN', use this as the bone to align with. This is a BoneInfo instance or a string. This is equivalent to the "Active Bone" alignment in Blender.
		self.roll_vector = Vector()		# If roll_type=='VECTOR', use this as the vector that the Z axis should point towards. This is equivalent to "Align to Cursor" in Blender.

		self._source = self

		if source:
			self.head = source.head.copy()
			self.tail = source.tail.copy()
			self.roll = source.roll
			self.envelope_distance = source.envelope_distance
			self.envelope_weight = source.envelope_weight
			self.use_envelope_multiply = source.use_envelope_multiply
			self.head_radius = source.head_radius
			self.tail_radius = source.tail_radius
			if type(source) == BoneInfo:
				self._source = source
				self.roll_type = source.roll_type
				self.roll_bone = source.roll_bone
				self.roll = source.roll
				self.bone_group = source.bone_group
				self.bbone_width = source.bbone_width
				if source.parent:
					self.parent = source.parent
			elif type(source) == EditBone:
				self.bbone_x = source.bbone_x
				self.bbone_z = source.bbone_z
				if source.parent:
					self.parent = source.parent.name	# TODO: The correct way to do this would be to load bones either in a hierarchical order, or to loop through them twice. Then we would no longer have to support strings as parents, and always use BoneInfo references.

		# Apply property values from arbitrary keyword arguments if any were passed.
		for key, value in kwargs.items():
			setattr(self, key, value)

	@property
	def name(self):
		return self._name

	@name.setter
	def name(self, value):
		new_name = value
		rig = self.bone_set.rig
		rig_ob = rig.obj
		bone = rig_ob.data.bones.get(self._name)
		if bone:
			generator = rig.generator
			del generator.bone_owners[self._name]
			generator.bone_owners[new_name] = rig
			bone.name = new_name
		self._name = new_name

	@property
	def source(self):
		"""The source is the ORG bone that this BoneInfo was copied from, or
		this BoneInfo itself.
		"""
		# Recursively get the source of each bone until getting to what should be an ORG bone.
		if self._source == self:
			return self
		return self._source.source

	@property
	def custom_shape_scale(self):
		return sum(self.custom_shape_scale_xyz)/3

	@custom_shape_scale.setter
	def custom_shape_scale(self, value):
		self.custom_shape_scale_xyz = Vector((value, value, value))

	@property
	def parent(self):
		return self._parent

	@parent.setter
	def parent(self, value):
		if self._parent and isinstance(self._parent, BoneInfo):
			self._parent.children.remove(self)
		self._parent = value
		if value and isinstance(value, BoneInfo):
			value.children.append(self)

	@property
	def bbone_width(self):
		"""Return average display size of both axes."""
		return (self.bbone_x+self.bbone_z)/2

	@bbone_width.setter
	def bbone_width(self, value):
		"""Set all bone size related values at once."""
		self.bbone_x = value
		self.bbone_z = value
		self.envelope_distance = value
		self.head_radius = value
		self.tail_radius = value

	@property
	def vector(self):
		"""Vector pointing from head to tail."""
		return self.tail-self.head

	@vector.setter
	def vector(self, value: Vector):
		self.tail = self.head + value

	def scale_width(self, value: int):
		"""Set b-bone width relative to current."""
		self.bbone_width *= value

	def scale_length(self, value: int):
		"""Set bone length relative to its current length."""
		self.tail = self.head + self.vector * value

	@property
	def length(self):
		return (self.tail-self.head).length

	@length.setter
	def length(self, value):
		assert value > 0, f"{self.name}: Bone length cannot be 0!"
		self.tail = self.head + self.vector.normalized() * value

	@property
	def center(self):
		return self.head + self.vector/2

	def reverse(self):
		"""Flip the head and the tail.""" # NOTE: What to do with roll, if there is one?
		self.head, self.tail = self.tail, self.head

	def set_layers(self, layerlist, additive=False):
		set_layers(self, layerlist, additive)

	def put(self, loc=None, length=None, width=None, scale_length=None, scale_width=None):
		if not loc:
			loc = self.head

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

	def flatten(self, axis=""):
		if axis:
			length = self.length
			if axis == 'X':
				self.tail.y = self.head.y
				self.tail.z = self.head.z
			elif axis == 'Y':
				self.tail.x = self.head.x
				self.tail.z = self.head.z
			elif axis == 'Z':
				self.tail.x = self.head.x
				self.tail.y = self.head.y
			self.length = length
		else:
			self.vector = flat(self.vector)

		from math import pi
		deg = self.roll*180/pi

		# Round to nearest 90 degrees.
		rounded = round(deg/90)*90
		self.roll = pi/180*rounded

	@property
	def custom_shape_along_length(self):
		"""Get custom widget display position as a factor along the bone's length."""
		if self.custom_shape_translation.y < 0.00001:
			return 0
		return self.length / self.custom_shape_translation.y

	@custom_shape_along_length.setter
	def custom_shape_along_length(self, value):
		"""Set custom widget display position as a factor along the bone's length."""
		self.custom_shape_translation.y = self.length * value

	def copy_custom_shape(self, other):
		if not other.custom_shape:
			return
		self.custom_shape = other.custom_shape
		self.custom_shape_translation = other.custom_shape_translation
		self.custom_shape_rotation_euler = other.custom_shape_rotation_euler
		self.custom_shape_scale_xyz = other.custom_shape_scale_xyz
		self.use_custom_shape_bone_size = other.use_custom_shape_bone_size
		self.use_custom_shape_bbone_scaling = False

	def get_constraint(self, name):
		for ci in self.constraint_infos:
			if ci.name == name:
				return ci

	def add_constraint(self, contype: str, index: int=None, **kwargs):
		"""Store constraint information about a constraint in this BoneInfo.
		contype: Type of constraint, eg. 'STRETCH_TO'.
		kwargs: Dictionary of properties and values.
		true_defaults: When False, we use a set of arbitrary default values that 
			I consider better than Blender's defaults.
		"""

		con_info = ConstraintInfo(self, contype, **kwargs)
		if index != None:
			self.constraint_infos.insert(index, con_info)
		else:
			self.constraint_infos.append(con_info)

		return con_info

	def add_constraint_from_real(self, constraint: Constraint):
		kwargs = {}
		skip = ['active', 'bl_rna', 'error_location', 'error_rotation', 
				'is_proxy_local', 'is_valid', 'rna_type', 'type']
		for key in dir(constraint):
			if "__" in key: continue
			if key in skip: continue
			value = getattr(constraint, key)

			if constraint.type=='ARMATURE' and key == 'targets':
				kwargs['targets'] = []
				for t in constraint.targets:
					kwargs['targets'].append({
						'target' : t.target,
						'subtarget' : t.subtarget,
						'weight' : t.weight
					})
				continue
			elif constraint.type == 'STRETCH_TO' \
				and key == 'rest_length' \
				and value == 0:
				continue

			kwargs[key] = value
			# HACK: Why is subtarget handled differently than space_subtarget?? Commit message includes "quick fix" so this probably needs a cleanup.
			if key == 'space_subtarget':
				kwargs[key] = kwargs[key].replace("ORG-", "")
		new_con = ConstraintInfo(self, constraint.type, **kwargs)
		new_con.is_from_real = True
		self.constraint_infos.append(new_con)
		return new_con

	def clear_constraints(self):
		self.constraint_infos = []

	def relink(self):
		"""Relinking a bone just means relinking its drivers, constraints and 
		constraint drivers."""
		# Relink bone drivers
		for d in self.drivers:
			self.bone_set.rig.relink_driver(d)

		for c in self.constraint_infos:
			c.relink()
			# Relink constraint drivers
			for d in c.drivers:
				self.bone_set.rig.relink_driver(d)

	def write_edit_data(self, generator, eb: EditBone, context: Context):
		"""Write relevant data of this BoneInfo into an EditBone."""
		# TODO: The fact that type annotating the generator would require a cyclic dependency suggests that this code belongs in the generator!
		armature = generator.obj
		assert armature.mode == 'EDIT', "Armature must be in Edit Mode when writing edit bone data."

		# Check for 0-length bones.
		if (self.head - self.tail).length == 0:
			# Warn and force length.
			self.bone_set.rig.add_log_bug("Bone with 0 length"
				,trouble_bone = self.name
				,description = "Bones cannot be created with a length of 0. Fell back to default vector."
			)
			self.tail = self.head+Vector((0, 0.1, 0))

		### Edit Bone properties
		for key in edit_bone_properties:
			key = key.replace("edit_", "")	# Allows bbone properties to specify if they are only for edit bone version
			if key.endswith("_axis"): continue # Read-only.
			value = self.__dict__[key]
			default_value = edit_bone_properties[key]
			if value == default_value:
			 	# For performance, don't write default values.
				continue
			setattr(eb, key, value)
		eb.use_connect = False	# NOTE: Without this, ORG- bones' Copy Transforms constraints can't work properly.

		scale = generator.scale
		eb.bbone_x = self.bbone_width * scale
		eb.bbone_z = self.bbone_width * scale
		eb.envelope_distance = self.bbone_width * scale
		eb.head_radius = self.bbone_width * scale
		eb.tail_radius = self.bbone_width * scale

		if self.parent:
			eb.parent = armature.data.edit_bones.get(str(self.parent))
			if not eb.parent:
				self.bone_set.rig.add_log("Parent not found"
					,trouble_bone=self.name
					,description=f'Parent bone "{self.parent}" does not exist or is a child of this bone.'
				)

		# Custom Properties.
		for prop_name, prop in self.custom_props_edit.items():
			make_property(eb, prop_name, **prop)

		# Recalculate roll.
		if self.roll_type != "":
			if self.roll_type == 'ALIGN':
				# NOTE: If you're looking at this code and wondering why your roll
				# is not aligned like it should be, it's probably because
				# `eb.roll += self.roll`` down below.
				# Make sure to set `self.roll = 0` if that's what you need.
				align_bone = armature.data.edit_bones.get(str(self.roll_bone))
				if not align_bone:
					self.owner_rig.raise_error(f"Could not find bone {self.roll_bone} to calculate roll of {eb.name}.")
				else:
					eb.align_roll(align_bone.z_axis)
			elif self.roll_type == 'VECTOR':
				eb.align_roll(self.roll_vector)

			eb.roll += self.roll

	def write_pose_data(self, pose_bone: PoseBone):
		"""Write relevant data of this BoneInfo into a PoseBone."""
		armature = pose_bone.id_data

		assert armature.mode != 'EDIT', "Armature cannot be in Edit Mode when writing pose data"

		# Pose bone data
		pb = pose_bone
		for key in pose_bone_properties:
			key = key.replace("pose_", "")	# Allows bbone properties to specify if they are only for pose bone version
			value = self.__dict__[key]
			default_value = pose_bone_properties[key]
			if value == default_value:
			 	# For performance, don't write default values.
				continue
			if value in [None, ""]: continue
			if key == 'custom_shape_transform':
				value = armature.pose.bones.get(value.name)
			if key == 'bone_group':
				value = armature.pose.bone_groups.get(self.bone_group)
			setattr(pb, key, value)

		# Reset pose
		pb.matrix_basis = Matrix.Identity(4)

		# Bone data
		b = pb.bone
		for key in bone_properties:
			value = self.__dict__[key]
			if value in [None, ""]: continue
			if 'bbone_custom_handle' in key:
				value = armature.data.bones.get(value.name)
			if key in ['bbone_x', 'bbone_z']:
				# TODO: To write bone shape scale data properly, we would need a reference to the generator.scale.
				# This would best be done if this function was in the generator rather than BoneInfo.
				continue

			setattr(b, key, value)

		if b.name.startswith("DEF") and not b.use_deform:
			self.bone_set.rig.add_log("Non-deforming DEF bone"
				,trouble_bone = self.name
				,description = f'Bone name "{self.name}" begins with "DEF" but Deform checkbox is not enabled. This bone will not be keyframed by the "Whole Character" keying set!'
				,operator = 'object.cloudrig_rename_bone'
				,op_kwargs = {'old_name': b.name}
			)

		def fixed_path(data_path):
			if not data_path.startswith("[") and not data_path.startswith("."):
				return "." + data_path
			return data_path

		def make_driver_safe(ob, *, target_id, **kwargs):
			try:
				make_driver(ob, target_id=target_id, **kwargs)
			except:
				del kwargs['index']
				make_driver(ob, target_id=target_id, **kwargs)

		# Constraints.
		for ci in self.constraint_infos:
			con = ci.make_real(pb)
			for driver_info in ci.drivers:
				driver_info['prop'] = f'pose.bones["{pb.name}"].constraints["{con.name}"]{fixed_path(driver_info["prop"])}'
				make_driver_safe(armature, target_id=armature, **driver_info)

		# Custom Properties.
		for prop_name, prop in self.custom_props.items():
			if 'value' in prop:
				pb[prop_name] = prop['value']
				del prop['value']
			else:
				pb[prop_name] = prop['default']

			if 'overridable' in prop:
				pb.property_overridable_library_set(f'["{prop_name}"]', prop['overridable'])
				del prop['overridable']

			for key, value in prop.items():
				try:
					pb.id_properties_ui(prop_name).update(**{key : value})
				except TypeError:
					# Python properties do not support UI data.
					break

		# Pose Bone Drivers.
		for driver_info in self.drivers:
			driver_info['prop'] = f'pose.bones["{pb.name}"]{fixed_path(driver_info["prop"])}'
			make_driver_safe(armature, target_id=armature, **driver_info)

		# Data Bone Drivers.
		for driver_info in self.drivers_data:
			driver_info['prop'] = f'bones["{pb.name}"]{fixed_path(driver_info["prop"])}'
			make_driver_safe(armature.data, target_id=armature, **driver_info)

	def clone(self, new_name=None, bone_set=None):
		"""Return a clone of self."""
		if not new_name:
			new_name = self.name + ".001"		# TODO: Properly find an avilable name (there's uniqify() for this in the Selection Sets addon, would be nice to move that to master.)

		if not bone_set:
			bone_set = self.bone_set

		new_bone = bone_set.new(
			name = new_name
		)

		for key, value in self.__dict__.items():
			if key=='name' or key.startswith("_"):
				continue
			value = getattr(self, key)
			if type(value) in [Vector, Matrix, dict]:
				setattr(new_bone, key, value.copy())
			elif type(value) in [list]:
				setattr(new_bone, key, value[:])
			else:
				setattr(new_bone, key, value)

		return new_bone

	def disown(self, new_parent):
		""" Parent all children of this bone to a new parent. """
		for b in self.children:
			b.parent = new_parent

	def get_real(self, rig: Object):
		"""If a bone with the name of this BoneInfo exists in the passed rig, 
		return it."""
		if rig.mode == 'EDIT':
			return rig.data.edit_bones.get(self.name)
		else:
			return rig.pose.bones.get(self.name)

	def __repr__(self):
		return self.name

	def __str__(self):
		return self.name

class ConstraintInfo(dict):
	"""Helper class to store and manage constraint info before it's passed to 
	Rigify's make_constraint()."""

	def __init__(self, bone_info, con_type, target=None, use_preferred_defaults=True, **kwargs):
		# Blame this guy https://stackoverflow.com/a/14620633/1527672
		super(ConstraintInfo, self).__init__(**kwargs)
		self.__dict__ = self

		self.type = con_type
		self.bone_info = bone_info	# BoneInfo to which this constraint is being added.
		self.target = target
		self.name = self.type.replace("_", " ").title()
		self.drivers = []

		self.is_from_real = False	# Whether this constraint was read from a real bpy.types.Constraint.

		if use_preferred_defaults:
			self.set_preferred_defaults()

		for key, value in kwargs.items():
			self.__dict__[key] = value

	def set_preferred_defaults(self):
		"""Set some arbitrary preferred defaults, separately from __init__(), 
		to keep this optional."""

		# Set target as the rig object, except for some constraint types.
		if self.type not in ['SPLINE_IK', 'LIMIT_LOCATION', 'LIMIT_SCALE',
							'LIMIT_ROTATION', 'SHRINKWRAP']:
			if hasattr(self.bone_info, 'rig') and self.target in [None, self.bone_info.owner_rig.generator.metarig]:
				self.target = self.bone_info.rig

		# Constraints that support local space should default to local space.
		support_local = ['COPY_LOCATION', 'COPY_SCALE', 'COPY_ROTATION', 'COPY_TRANSFORMS',
						'LIMIT_LOCATION', 'LIMIT_SCALE', 'LIMIT_ROTATION',
						'ACTION', 'TRANSFORM']
		if not hasattr(self, 'space') and self.type in support_local:
			self.space = 'LOCAL'

		if self.type == 'TRANSFORM':
			self.mix_mode_scale = 'MULTIPLY'
			self.mix_mode_rot = 'BEFORE'
		if self.type == 'STRETCH_TO':
			self.use_bulge_min = True
			self.use_bulge_max = True
			self.rest_length = self.bone_info.length
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

	def relink(self):
		"""Allow the Rigify relink naming convention of an @ symbol separating 
		the constraint name from a list of subtargets separated by commas."""

		rig_element = self.bone_info.bone_set.rig
		rig = rig_element.obj
		metarig = rig_element.generator.metarig

		if "@" not in self.name:
			if self.type=='ARMATURE':
				for i, t in enumerate(self.targets):
					if t == metarig:
						t['target'] = rig
					if 'target' not in self.targets[i] or not self.targets[i]['target']:
						t['target'] = rig
			return

		split_name = self.name.split("@")
		subtargets = split_name[1:]
		self.name = split_name[0]

		if self.type=='ARMATURE':
			if len(self.targets) > len(subtargets):
				self.bone_info.owner_rig.add_log(
					"Relinking failed",
					trouble_bone = self.bone_info.name,
					description  = f'Failed to relink constraint due to too many targets in constraint "{self.name}".\n Remove unneeded targets from the Armature constraint!'
				)
				return

			for i, t in enumerate(self.targets):
				t['subtarget'] = subtargets[i]
				if not t['target']:
					t['target'] = rig
			return

		if len(subtargets) > 0:
			self.subtarget = subtargets[0]

	def make_real(self, pose_bone):
		""" Create a constraint based on this ConstraintInfo on a given pose bone. """
		con_info = self.__dict__.copy()
		for key in ['type', 'bone_info', 'drivers', 'is_from_real', 'is_override_data']:
			if key in con_info:
				del con_info[key]

		# List of ID + string tuples that define a constraint target. 
		# The string is an optional "subtarget" (bone or vgroup name)
		target_pairs: List[Tuple["bpy.types.ID", str]] = []
		if 'targets' in con_info:
			for target_info in con_info['targets']:
				assert 'subtarget' in target_info, f"Armature constraint with no subtarget: {pose_bone.name}"
				if 'target' not in target_info:
					# Allow omitting target object from Armature contraint targets.
					target_info['target'] = pose_bone.id_data
				if isinstance(target_info['subtarget'], BoneInfo):
					# Allow using BoneInfo instances, convert them to string here.
					target_info['subtarget'] = target_info['subtarget'].name
			target_pairs = [(t['target'], t['subtarget']) for t in con_info['targets']]
		elif 'target' in con_info:
			target_pairs = [[con_info['target'], ""]]

		if 'subtarget' in con_info:
			if isinstance(con_info['subtarget'], BoneInfo):
				# Allow using BoneInfo instances, convert them to string here.
				con_info['subtarget'] = con_info['subtarget'].name

			# Singular target, target object is optional, assumed to be the rig.
			target = target_pairs[0][0]
			if not target:
				target = pose_bone.id_data
			target_pairs = [(target, con_info['subtarget'])]

		for target_pair in target_pairs:
			target, subtarget = target_pair
			if (target and target.type=='ARMATURE') and (subtarget not in target.data.bones):
				self.bone_info.owner_rig.add_log("Invalid constraint target!"
					,owner_bone   = self.bone_info.name
					,trouble_bone = subtarget
					,description  = f'Constraint "{self.name}" on bone "{self.bone_info}" has non-existent target bone {subtarget} in {target}.'
				)

		con = make_constraint(pose_bone, self.type, **con_info)

		return con
