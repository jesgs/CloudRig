# Data Container and utilities for de-coupling bone creation and setup from BPY.
# Lets us easily create bones without having to worry about edit/pose mode.
import bpy
from mathutils import Vector
import copy
from ..rigs import cloud_utils
from rigify.utils.mechanism import make_constraint, make_driver, make_property

class BoneSet(list):
	""" Class to manage lists of BoneInfo instances. 
	Also manages a bone group and layer assignment for these bones. """

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

	def __init__(self, generator, ui_name="Bone Set",
			bone_group="Group", normal=None, select=None, active=None, preset=-1,
			layers = [l==0 for l in range(32)],
			defaults = {}
	):
		# Rigify BaseRig instance where this BoneSet is used, and should be stored.
		self.generator = generator
		self.scale = generator.scale

		# kwargs that should always be passed to bones created in this bone set.
		self.defaults = defaults

		# Name that will be displayed in the Bone Sets UI.
		self.ui_name = ui_name
		
		# Bone Group name to assign to newly defined BoneInfos.
		self.bone_group = bone_group

		# Layers to assign to newly defined BoneInfos.
		self.layers = layers

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

	def new(self, name="Bone", source=None, **kwargs):
		"""Define a bone and add it to the list of bones."""

		# TODO: cloud_utils.new_bone(bone_set, bone_name, kwargs) should do this checking?
		# bi = self.riglet.get_bone_info(name)
		# if bi:
		# 	print(f"Warning: BoneInfo {name} already exists in BoneSet: {bi.bone_set}.")
		# 	name += ".001"
		# 	while(self.riglet.get_bone_info(name)):
		# 		num = int(name[-1])
		# 		name = name[:-4] + str(num+1).zfill(3)
		# 	print(f"Added as {name} to {self.ui_name}")

		if 'bone_group' not in kwargs:
			kwargs['bone_group'] = self.bone_group
		if 'layers' not in kwargs:
			kwargs['layers'] = self.layers
		for key in self.defaults.keys():
			if key not in kwargs:
				kwargs[key] = self.defaults[key]

		bi = BoneInfo(self, name, source, **kwargs)
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

class BoneInfo():
	""" 
	The purpose of this class is to abstract bpy.types.Bone, bpy.types.PoseBone and bpy.types.EditBone
	into a single concept.

	This class does not concern itself with posing the bone, only creating and rigging it.
	Eg, it does not store pose bone transformations such as loc/rot/scale. 
	"""

	def __init__(self, container, name="Bone", source=None, **kwargs):
		""" 
		container: Need a reference to what BoneSet this BoneInfo belongs to. #TODO: might be nice to make this not required?
		source:	Bone to take transforms from (head, tail, roll, bbone_x, bbone_z).
		kwargs: Allow setting arbitrary bone properties at initialization.
		"""

		self.container = container

		self.custom_props = {}	# {"name" : {kwargs}} where kwargs will be passed to Rigify's make_property().
		self.custom_props_edit = {}
		self.drivers = []		# List of dictionaries that will be passed to Rigify's make_driver().
		self.drivers_data = []	# Same but for data bone properties.

		self.constraint_infos = [] # List of ConstraintInfo objects. Their __dict__ will be passed to Rigify's make_constraint().

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
		self.bone_group = ""		# Blender expects bpy.types.BoneGroup, we store str.
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
				self.bone_group = source.bone_group
				self.bbone_width = source.bbone_width
			else:
				self._bbone_x = source.bbone_x
				self._bbone_z = source.bbone_z
			if source.parent:
				if type(source)==bpy.types.EditBone:
					self.parent = source.parent.name
				else:
					self.parent = source.parent 

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
	def vector(self):
		"""Vector pointing from head to tail."""
		return self.tail-self.head

	@vector.setter
	def vector(self, value):
		self.tail = self.head + value

	def scale_width(self, value):
		"""Set bbone width relative to current."""
		self.bbone_width *= value

	def scale_length(self, value):
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
		self.vector = cloud_utils.flat(self.vector)
		from math import pi
		deg = self.roll*180/pi
		# Round to nearest 90 degrees.
		rounded = round(deg/90)*90
		self.roll = pi/180*rounded

	def disown(self, new_parent):
		""" Parent all children of this bone to a new parent. """
		# TODO: make self.parent a @property so bones are aware of their children!
		for b in self.container.bones:
			if b.parent==self or b.parent==self.name:
				b.parent = new_parent

	def get_constraint(self, name):
		for ci in self.constraint_infos:
			if ci.name == name:
				return ci

	def add_constraint(self, contype, index=None, **kwargs):
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
		"""Write relevant data of this BoneInfo into an EditBone."""
		assert armature.mode == 'EDIT', "Error: Armature must be in Edit Mode when writing edit bone data."

		# Check for 0-length bones.
		if (self.head - self.tail).length == 0:
			# Warn and force length.
			print("Warning: Had to force 0-length bone to have some length: " + self.name)
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
		for prop_name, prop in self.custom_props_edit.items():
			make_property(eb, prop_name, **prop)

	def write_pose_data(self, pose_bone):
		"""Write relevant data of this BoneInfo into a PoseBone."""
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

		# Bone Group
		if type(self.bone_group)==str and self.bone_group!="":
			pb.bone_group = armature.pose.bone_groups.get(self.bone_group)

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
	
	def get_real(self, armature):
		"""If a bone with the name of this BoneInfo exists in the passed armature, return it."""
		if armature.mode == 'EDIT':
			return armature.data.edit_bones.get(self.name)
		else:
			return armature.pose.bones.get(self.name)

class ConstraintInfo:
	"""Helper class to store and manage constraint info before it's passed to Rigify's make_constraint."""

	def __init__(self, bone_info, con_type, target=None, use_preferred_defaults=True, **kwargs):
		self.type = con_type
		self.bone_info = bone_info	# BoneInfo to which this constraint is being added.
		self.target = target
		self.name = self.type.replace("_", " ").title()
		self.drivers = []
		
		for key, value in kwargs.items():
			self.__dict__[key] = value

		if use_preferred_defaults:
			self.set_preferred_defaults()

	def set_preferred_defaults(self):
		"""Set some arbitrary preferred defaults, separately from __init__(), to keep this optional."""

		# Set target as the rig object, except for some constraint types.
		if self.type not in ['SPLINE_IK', 'LIMIT_LOCATION', 'LIMIT_SCALE', 'LIMIT_ROTATION', 'SHRINKWRAP']:
			self.target = self.bone_info.container.generator.obj

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
	
	def make_real(self, pose_bone):
		""" Create a constraint based on this ConstraintInfo on a given pose bone. """
		con_type = self.type
		con_info = self.__dict__.copy()
		for key in ['type', 'bone_info', 'drivers']:
			del con_info[key]

		targets = None
		if con_type == 'ARMATURE' and 'targets' in con_info:
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