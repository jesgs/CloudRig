from typing import Dict, List

import bpy
from bpy.props import StringProperty, BoolVectorProperty
from mathutils import Vector
import copy
from collections import OrderedDict

from .utils.maths import flat
from .utils.object import set_layers
from rigify.utils.mechanism import make_constraint, make_driver, make_property

edit_bone_properties = {
	'head' : Vector((0, 0, 0))
	,'tail' : Vector((0, 0, 1))
	,'roll' : 0
	,'head_radius' : 0.1
	,'tail_radius' : 0.1
	,'use_connect' : False

	,'bbone_curveinx' : 0
	,'bbone_curveiny' : 0
	,'bbone_curveoutx' : 0
	,'bbone_curveouty' : 0
	,'bbone_easein' : 1
	,'bbone_easeout' : 1
	,'bbone_scaleinx' : 1
	,'bbone_scaleiny' : 1
	,'bbone_scaleoutx' : 1
	,'bbone_scaleouty' : 1
}

bone_properties = {
	'name' : "Bone"
	,'layers' : [l==0 for l in range(32)]	# 32 bools where only the first one is True.
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
	,'bbone_custom_handle_end': None		# BoneInfo

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
	,'custom_shape_scale' : 1.0
	,'use_custom_shape_bone_size' : False

	,'rotation_mode' : 'QUATERNION'
	,'lock_location' : [False, False, False]
	,'lock_rotation' : [False, False, False]
	,'lock_rotation_w' : False
	,'lock_scale' : [False, False, False]
}

class LinkedList(list):
	"""Some very basic doubly linked list functionality to help manage chains of bones."""
	def __init__(self):
		super().__init__()
		self.first = self.last = None

	def remove(self, value):
		super().remove(value)
		if value.prev:
			value.prev.next = value.next
		if value.next:
			value.next.prev = value.prev

	def append(self, value):
		if len(self)>0:
			self[-1].next = value
			value.prev = self[-1]
		super().append(value)

class BoneSet(LinkedList):
	""" Class to create and store lists of BoneInfo instances.
		Can also assign a bone group and set of layers for the created bones.
	"""

	presets = [
		[(0.6039215922355652, 0.0, 0.0), (0.7411764860153198, 0.06666667014360428, 0.06666667014360428), (0.9686275124549866, 0.03921568766236305, 0.03921568766236305)],
		[(0.9686275124549866, 0.250980406999588, 0.0941176563501358), (0.9647059440612793, 0.4117647409439087, 0.07450980693101883), (0.9803922176361084, 0.6000000238418579, 0.0)],
		[(0.11764706671237946, 0.5686274766921997, 0.03529411926865578), (0.3490196168422699, 0.7176470756530762, 0.04313725605607033), (0.5137255191802979, 0.9372549653053284, 0.11372549831867218)],
		[(0.03921568766236305, 0.21176472306251526, 0.5803921818733215), (0.21176472306251526, 0.40392160415649414, 0.874509871006012), (0.3686274588108063, 0.7568628191947937, 0.9372549653053284)],
		[(0.6627451181411743, 0.16078431904315948, 0.30588236451148987), (0.7568628191947937, 0.2549019753932953, 0.41568630933761597), (0.9411765336990356, 0.364705890417099, 0.5686274766921997)],
		[(0.26274511218070984, 0.0470588281750679, 0.4705882668495178), (0.3294117748737335, 0.22745099663734436, 0.6392157077789307), (0.529411792755127, 0.3921568989753723, 0.8352941870689392)],
		[(0.1411764770746231, 0.4705882668495178, 0.3529411852359772), (0.2352941334247589, 0.5843137502670288, 0.4745098352432251), (0.43529415130615234, 0.7137255072593689, 0.6705882549285889)],
		[(0.29411765933036804, 0.4392157196998596, 0.4862745404243469), (0.41568630933761597, 0.5254902243614197, 0.5686274766921997), (0.6078431606292725, 0.760784387588501, 0.803921639919281)],
		[(0.9568628072738647, 0.7882353663444519, 0.0470588281750679), (0.9333333969116211, 0.760784387588501, 0.21176472306251526), (0.9529412388801575, 1.0, 0.0)],
		[(0.11764706671237946, 0.125490203499794, 0.1411764770746231), (0.2823529541492462, 0.2980392277240753, 0.33725491166114807), (1.0, 1.0, 1.0)],
		[(0.43529415130615234, 0.18431372940540314, 0.41568630933761597), (0.5960784554481506, 0.2705882489681244, 0.7450980544090271), (0.8274510502815247, 0.1882353127002716, 0.8392157554626465)],
		[(0.4235294461250305, 0.5568627715110779, 0.13333334028720856), (0.49803924560546875, 0.6901960968971252, 0.13333334028720856), (0.7333333492279053, 0.9372549653053284, 0.35686275362968445)],
		[(0.5529412031173706, 0.5529412031173706, 0.5529412031173706), (0.6901960968971252, 0.6901960968971252, 0.6901960968971252), (0.8705883026123047, 0.8705883026123047, 0.8705883026123047)],
		[(0.5137255191802979, 0.26274511218070984, 0.14901961386203766), (0.545098066329956, 0.3450980484485626, 0.06666667014360428), (0.7411764860153198, 0.41568630933761597, 0.06666667014360428)],
		[(0.0313725508749485, 0.19215688109397888, 0.05490196496248245), (0.1098039299249649, 0.26274511218070984, 0.04313725605607033), (0.2039215862751007, 0.38431376218795776, 0.16862745583057404)],
	]

	def __init__(self, ui_name="Bone Set",
			bone_group="Group", normal=None, select=None, active=None, preset=-1,
			layers = [l==0 for l in range(32)],
			defaults = {}
	):
		super().__init__()

		# kwargs that will be passed to new BoneInfo() instances.
		self.defaults = defaults

		# Name that will be displayed in the Bone Sets UI.
		self.ui_name = ui_name

		# Layers to assign to newly defined BoneInfos.
		self.layers = layers

		# Bone Group name to assign to newly defined BoneInfos.
		self.bone_group = bone_group

		self.color_set = 'CUSTOM'
		self.normal = [0, 0, 0]
		self.select = [0, 0, 0]
		self.active = [0, 0, 0]

		presets = type(self).presets

		if len(presets) > preset > -1:
			self.normal = presets[preset][0]
			self.select = presets[preset][1]
			self.active = presets[preset][2]
		else:
			if not normal and not select and not active:
				self.color_set = 'DEFAULT'

		if normal: self.normal = normal
		if select: self.select = select
		if active: self.active = active

	def find(self, name):
		"""Find a BoneInfo instance by name, return it if found."""
		for bi in self:
			if(bi.name == name):
				return bi
		return None

	def __repr__(self):
		return f"{self.ui_name}: {super().__repr__()}"

	def new(self, name="Bone", source=None, **kwargs):
		"""Create and add a new BoneInfo to self."""

		if 'bone_group' not in kwargs:
			kwargs['bone_group'] = self.bone_group
		if 'layers' not in kwargs:
			kwargs['layers'] = self.layers
		for key in self.defaults.keys():
			if key not in kwargs:
				kwargs[key] = self.defaults[key]

		bi = BoneInfo(name, source, **kwargs)
		self.append(bi)

		return bi

	def ensure_bone_group(self, rig, overwrite=False):
		""" Create the bone group defined by this bone set on rig. """

		bone_group = rig.pose.bone_groups.get(self.bone_group)
		if bone_group and not overwrite:
			return bone_group

		if not bone_group:
			bone_group = rig.pose.bone_groups.new(name=self.bone_group)

		bone_group.color_set = self.color_set
		bone_group.colors.normal = self.normal[:]
		bone_group.colors.select = self.select[:]
		bone_group.colors.active = self.active[:]

		return bone_group

class BoneInfo:
	"""
	The purpose of this class is to abstract bpy.types.Bone, bpy.types.PoseBone 
	and bpy.types.EditBone into a single concept.

	This class does not concern itself with posing the bone, only creating and 
	rigging it. Eg, it does not store transformations such as loc/rot/scale.
	"""

	@staticmethod
	def from_real(rig: bpy.types.Object, edit_bone: bpy.types.EditBone):
		"""Load a bpy bone into a BoneInfo class along with its constraints, drivers, custom properties."""
		# NOTE: Parenting should be set outside of this function.

		pose_bone = rig.pose.bones.get(edit_bone.name)
		data_bone = pose_bone.bone
		bone_info = BoneInfo(edit_bone.name, source=edit_bone, layers=data_bone.layers[:])

		for key in pose_bone_properties:
			value = getattr(pose_bone, key)
			if value in [None, ""]: continue
			if key=='bone_group':
				value = value.name
			setattr(bone_info, key, value)
		for key in bone_properties:
			setattr(bone_info, key, getattr(data_bone, key))
		for key in edit_bone_properties:
			value = getattr(edit_bone, key)
			if type(value)==Vector:
				value = value.copy()
			setattr(bone_info, key, value)

		# Remove constraints from the bone and load them into the BoneInfo so they can be read and modified.
		for c in pose_bone.constraints:
			ci = bone_info.add_constraint_from_real(c)
			pose_bone.constraints.remove(c)
		
		# TODO: drivers, custom properties.
		return bone_info

	def __init__(self, name="Bone", source: bpy.types.EditBone or BoneInfo = None, **kwargs):
		"""
		source:	Bone to take transforms from (head, tail, roll, bbone_x, bbone_z).
		kwargs: Allow setting arbitrary bone properties at initialization.
		"""

		self.owner_rig = None	# This should be set after creating the instance!
		self.next = self.prev = None	# for LinkedList behaviour.

		self.custom_props = {}	# {"name" : {kwargs}} where kwargs will be passed to Rigify's make_property().
		self.custom_props_edit = {}
		self.drivers = []		# List of dictionaries that will be passed to Rigify's make_driver().
		self.drivers_data = []	# Same but for data bone properties.

		self.constraint_infos = [] # List of ConstraintInfo objects. Their __dict__ will be passed to Rigify's make_constraint().

		### Edit Bone properties
		for key in edit_bone_properties.keys():
			setattr(self, key, edit_bone_properties[key])
		self._parent = None
		self.children: List[BoneInfo] = []

		### Bone properties
		for key in bone_properties.keys():
			setattr(self, key, bone_properties[key])

		### Pose Bone properties
		for key in pose_bone_properties.keys():
			setattr(self, key, pose_bone_properties[key])

		self.name=name

		# Recalculate Roll
		self.roll_type = "" # This will be passed as the "type" parameter to bpy.ops.armature.calculate_roll().
		self.roll_bone = None # If roll_type=='ACTIVE', use this as the active bone. This is a BoneInfo instance or a string.
		self.roll_cursor = Vector() # If roll_type=='CURSOR', use this as the cursor location.

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
				self.bone_group = source.bone_group
				self.bbone_width = source.bbone_width
			else:
				self.bbone_x = source.bbone_x
				self.bbone_z = source.bbone_z
			if source.parent:
				if type(source)==BoneInfo:
					self.parent = source.parent
				else:
					self.parent = source.parent.name

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

	def __repr__(self):
		return self.name

	def __str__(self):
		return self.name

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
		return self.bbone_x

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
		assert value > 0, "Length cannot be 0!"
		self.tail = self.head + self.vector.normalized() * value

	@property
	def center(self):
		return self.head + self.vector/2

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

	def flatten(self):
		self.vector = flat(self.vector)
		from math import pi
		deg = self.roll*180/pi
		# Round to nearest 90 degrees.
		rounded = round(deg/90)*90
		self.roll = pi/180*rounded

	def disown(self, new_parent):
		""" Parent all children of this bone to a new parent. """
		for b in self.children:
			b.parent = new_parent

	def get_constraint(self, name):
		for ci in self.constraint_infos:
			if ci.name == name:
				return ci

	def add_constraint(self, contype: str, index: int=None, **kwargs):
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

	def add_constraint_from_real(self, constraint: bpy.types.Constraint):
		kwargs = {}
		skip = ['active', 'bl_rna', 'error_location', 'error_rotation', 'is_proxy_local', 'is_valid', 'rna_type', 'type']
		for key in dir(constraint):
			if "__" in key: continue
			if key in skip: continue

			if key=='targets' and constraint.type=='ARMATURE':
				kwargs['targets'] = []
				for t in constraint.targets:
					kwargs['targets'].append({
						'target' : constraint.id_data,
						'subtarget' : t.subtarget,
						'weight' : t.weight
					})
				continue

			kwargs[key] = getattr(constraint, key)

		new_con = ConstraintInfo(self, constraint.type, **kwargs)
		self.constraint_infos.append(new_con)
		return new_con

	def clear_constraints(self):
		self.constraint_infos = []

	def write_edit_data(self, armature: bpy.types.Armature, edit_bone: bpy.types.EditBone):
		"""Write relevant data of this BoneInfo into an EditBone."""
		assert armature.mode == 'EDIT', "Armature must be in Edit Mode when writing edit bone data."

		# Check for 0-length bones.
		if (self.head - self.tail).length == 0:
			# Warn and force length.
			self.generator.logger.log_bug("Bone with 0 length"
				,trouble_bone = self.name
				,description = "Bones cannot be created with a length of 0. Fell back to default vector."
			)
			self.tail = self.head+Vector((0, 0.1, 0))

		### Edit Bone properties
		eb = edit_bone

		for key in edit_bone_properties:
			setattr(eb, key, self.__dict__[key])
		eb.use_connect = False	# NOTE: Without this, ORG- bones' Copy Transforms constraints can't work properly.

		if self.parent:
			eb.parent = armature.data.edit_bones.get(str(self.parent))

		# Custom Properties.
		for prop_name, prop in self.custom_props_edit.items():
			make_property(eb, prop_name, **prop)

		# Recalculate roll.
		cursor_backup = bpy.context.scene.cursor.location.copy()
		if self.roll_type != "":
			bpy.ops.armature.select_all(action='DESELECT')
			eb.select = True
			if self.roll_type == 'ACTIVE':
				active_bone = armature.data.edit_bones.get(str(self.roll_bone))
				if not active_bone:
					self.owner_rig.raise_error(f"Could not find bone {self.roll_bone} to calculate roll of {eb.name}.")
				else:
					armature.data.edit_bones.active = active_bone
			elif self.roll_type == 'CURSOR':
				bpy.context.scene.cursor.location = self.roll_cursor

			bpy.ops.armature.calculate_roll(type=self.roll_type)
			eb.roll += self.roll
			bpy.context.scene.cursor.location = cursor_backup

	def write_pose_data(self, pose_bone: bpy.types.PoseBone):
		"""Write relevant data of this BoneInfo into a PoseBone."""
		armature = pose_bone.id_data

		assert armature.mode != 'EDIT', "Armature cannot be in Edit Mode when writing pose data"

		# Pose bone data
		pb = pose_bone
		for key in pose_bone_properties:
			value = self.__dict__[key]
			if value in [None, ""]: continue
			if key=='custom_shape_transform':
				value = armature.pose.bones.get(value.name)
			if key=='bone_group':
				value = armature.pose.bone_groups.get(self.bone_group)
			setattr(pb, key, value)

		# Bone data
		b = pb.bone
		for key in bone_properties:
			value = self.__dict__[key]
			if value in [None, ""]: continue
			if 'bbone_custom_handle' in key:
				value = armature.data.bones.get(value.name)

			setattr(b, key, value)

		# Constraints.
		for ci in self.constraint_infos:
			con = ci.make_real(pb)
			for driver_info in ci.drivers:
				driver_info['prop'] = f'pose.bones["{pb.name}"].constraints["{con.name}"].{driver_info["prop"]}'
				make_driver(armature, target_id=armature, **driver_info)

		# Custom Properties.
		for prop_name, prop in self.custom_props.items():
			make_property(pb, prop_name, **prop)

		# Pose Bone Drivers.
		for driver_info in self.drivers:
			driver_info['prop'] = f'pose.bones["{pb.name}"].{driver_info["prop"]}'
			make_driver(armature, target_id=armature, **driver_info)

		# Data Bone Drivers.
		for driver_info in self.drivers_data:
			driver_info['prop'] = f'bones["{pb.name}"].{driver_info["prop"]}'
			make_driver(armature.data, target_id=armature, **driver_info)

	def get_real(self, rig: bpy.types.Object):
		"""If a bone with the name of this BoneInfo exists in the passed rig, return it."""
		if rig.mode == 'EDIT':
			return rig.data.edit_bones.get(self.name)
		else:
			return rig.pose.bones.get(self.name)

class ConstraintInfo(dict):
	"""Helper class to store and manage constraint info before it's passed to Rigify's make_constraint."""

	def __init__(self, bone_info, con_type, target=None, use_preferred_defaults=True, **kwargs):
		# Blame this guy https://stackoverflow.com/a/14620633/1527672
		super(ConstraintInfo, self).__init__(**kwargs)
		self.__dict__ = self

		self.type = con_type
		self.bone_info = bone_info	# BoneInfo to which this constraint is being added.
		self.target = target
		self.name = self.type.replace("_", " ").title()
		self.drivers = []

		if use_preferred_defaults:
			self.set_preferred_defaults()

		for key, value in kwargs.items():
			self.__dict__[key] = value

	def set_preferred_defaults(self):
		"""Set some arbitrary preferred defaults, separately from __init__(), to keep this optional."""

		# Set target as the rig object, except for some constraint types.
		if self.type not in ['SPLINE_IK', 'LIMIT_LOCATION', 'LIMIT_SCALE', 
							'LIMIT_ROTATION', 'SHRINKWRAP']:
			if hasattr(self.bone_info, 'rig'):
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
		"""Allow the Rigify relink naming convention of an @ symbol separating the constraint name from a list of subtargets separated by commas."""
		split_name = self.name.split("@")
		subtargets = split_name[1:]
		self.name = split_name[0]

		if self.type=='ARMATURE':
			if len(self.targets) > len(subtargets):
				self.bone_info.owner_rig.add_log(
					"Relinking failed", 
					trouble_bone = self.bone_info.name, 
					description=f"Failed to relink constraint due to too many targets in constraint {self.name}.\n Remove unneeded targets from the Armature constraint!"
				)
				return

			for i, t in enumerate(self.targets):
				t['subtarget'] = subtargets[i]
			return

		if len(subtargets) > 0:
			self.subtarget = subtargets[0]

	def make_real(self, pose_bone):
		""" Create a constraint based on this ConstraintInfo on a given pose bone. """
		con_type = self.type
		con_info = self.__dict__.copy()
		for key in ['type', 'bone_info', 'drivers']:
			del con_info[key]
		
		subtargets = []
		if 'subtarget' in con_info:
			subtargets = [con_info['subtarget']]
		if 'targets' in con_info:
			subtargets = [t['subtarget'] for t in con_info['targets']]

		# TODO this armature constraint hackaround can be removed once D9092 is in. 
		# This will break backwards compatibility with prior blender versions.
		targets = None
		if con_type == 'ARMATURE' and 'targets' in con_info:
			targets = con_info['targets']
			del con_info['targets']
			del con_info['target']

		for i, subtarget in enumerate(subtargets):
			if subtarget not in pose_bone.id_data.data.bones:
				self.bone_info.owner_rig.add_log("Invalid constraint target!"
					,owner_bone = self.bone_info.name
					,trouble_bone = subtarget
					,description = f"Constraint {self.name} on bone {self.bone_info} has non-existent target bone {subtarget}."
				)
				if targets:
					targets[i]['subtarget'] = ""
				elif 'subtarget' in con_info:
					con_info['subtarget'] = ""
				else:
					return

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

def new_bonei(generator, bone_set: BoneSet = None, name="Bone", overwrite=False, **kwargs) -> BoneInfo:
	""" Create a BoneInfo, optionally as part of a BoneSet.
		Ideally all bones should be part of a BoneSet
	"""
	new = None

	# If a BoneInfo with the passed name already exists, overwrite it and add a warning.
	bi = generator.find_bone_info(name)
	if bi and not overwrite:
		generator.logger.log_bug("Overwritten bone"
			,owner_bone = bi.owner_rig.meta_base_bone.name
			,trouble_bone = bi.name
			,description = "Bone was defined twice."
		)

	kwargs['name'] = name
	if bone_set is not None:
		kwargs['bone_set'] = bone_set
		new = bone_set.new(**kwargs)
	else:
		generator.logger.log_bug("Bone without BoneSet"
			,trouble_bone = name
			,description = "BoneInfo was created without a BoneSet."
		)
		new = BoneInfo(**kwargs)

	generator.bone_infos.append(new)
	new.generator = generator
	return new

class BoneInfoMixin:
	""" This class should be used for implementing BoneInfo and BoneSet
		use in a rig.
	"""

	bone_set_defs: Dict[str, str] = OrderedDict()

	def new_bonei(self, bone_set: BoneSet = None, name="Bone", **kwargs) -> BoneInfo:
		new = new_bonei(self.generator, bone_set, name, **kwargs)
		new.owner_rig = self
		self.all_bones.append(new)
		return new

	def ensure_bone_set(self, bone_set_name):
		"""Take a bone set definition stored in the class and create a real BoneSet object for it on self."""
		bone_set_defs = type(self).bone_set_defs

		if not bone_set_name in bone_set_defs:
			msg = f"Error: Bone Set definition named {bone_set_name} not found in class {type(self)}. Could not create Bone Set. Report a bug!"
			self.add_log_bug("Bone Set Error", description=msg)
			assert False, msg

		bone_set_def = bone_set_defs[bone_set_name]

		bone_set_def['layers'] = getattr(self.params, bone_set_def['layer_param'])

		# Handle layer overrides for DEF/MCH/ORG from generator parameters.
		cloudrig = self.generator_params.cloudrig_parameters
		if bone_set_def['override'] == 'DEF' and cloudrig.override_def_layers:
			bone_set_def['layers'] = cloudrig.def_layers[:]

		if bone_set_def['override'] == 'MCH' and cloudrig.override_mch_layers:
			bone_set_def['layers'] = cloudrig.mch_layers[:]

		if bone_set_def['override'] == 'ORG' and cloudrig.override_org_layers:
			bone_set_def['layers'] = cloudrig.org_layers[:]

		new_set = BoneSet(
			ui_name = bone_set_def['name'],
			bone_group = getattr(self.params, bone_set_def['param']),
			layers = bone_set_def['layers'],
			preset = bone_set_def['preset'],
			defaults = self.defaults
		)

		self.generator.bone_sets.append(new_set)
		self.bone_sets.append(new_set)

		return new_set

	##############################
	# Parameters

	@classmethod
	def define_bone_set(cls, params, ui_name, default_group="", default_layers=[0], override="", preset=-1):
		"""
		A bone set is a set of rig parameters for choosing a bone group and list of bone layers.
		This function is responsible for creating those rig parameters, as well as storing them,
		so they can be referenced easily when implementing the creation of a new bone
		and assigning its bone group and layers.

		For example, all FK chain bones of the FK chain rig are hard-coded to be part of the "FK Main" bone set.
		Then the "FK Main" bone set's bone group and bone layer can be customized via the parameters.
		"""

		group_name = ui_name.replace(" ", "_").lower()
		if default_group=="":
			default_group = ui_name

		param_name = "CR_BG_" + group_name.replace(" ", "_")
		layer_param_name = "CR_BG_LAYERS_" + group_name.replace(" ", "_")

		setattr(
			params,
			param_name,
			StringProperty(
				default = default_group,
				description = f"Select what group {ui_name} should be assigned to"
			)
		)

		default_layers_bools = [i in default_layers for i in range(32)]
		setattr(
			params,
			layer_param_name,
			BoolVectorProperty(
				size = 32,
				subtype = 'LAYER',
				description = f"Select what layers {ui_name} should be assigned to",
				default = default_layers_bools
			)
		)

		assert override in ['', 'DEF', 'MCH', 'ORG'], "Unsupported bone set override"

		cls.bone_set_defs[ui_name] = {
			'name'			: ui_name
			,'preset'		: preset			# Bone Group color preset to use in case the bone group doesn't already exist.
			,'param' 	 	: param_name		# Name of the bone group name parameter
			,'layer_param'	: layer_param_name	# Name of the bone layers parameter
			,'override'		: override
		}
		return ui_name

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		cls.bone_set_defs = OrderedDict()