# Typing
import bpy
from ..rig_features.bone import BoneInfo
from typing import List

# CloudBaseRig parent classes
from rigify.base_rig import BaseRig
from ..rig_features.bone_set import BoneSetMixin
from ..rig_features.ui import CloudUIMixin
from ..rig_features.mechanism import CloudMechanismMixin
from ..rig_features.object import CloudObjectUtilitiesMixin
from ..rig_features.parent_switching import CloudParentSwitchMixin

# The rest
from bpy.props import BoolProperty, StringProperty, EnumProperty
from mathutils import Vector

class DEFAULT_LAYERS:
	IK_MAIN = 0
	IK_SECOND = 16
	FK_MAIN = 1
	FK_SECOND = 17

	STRETCH = 2
	DEF_CTR = 18

	FACE_MAIN = 3
	FACE_SECOND = 19

	DEF = 29
	MCH = 30
	ORG = 31

	FACE_TWEAK = 20

class CloudBaseRig(
					BaseRig,
					CloudParentSwitchMixin,
					CloudMechanismMixin,
					CloudObjectUtilitiesMixin,
					CloudUIMixin,
					BoneSetMixin,
	):
	"""Base class that all CloudRig rigs should inherit from."""

	DEFAULT_LAYERS = DEFAULT_LAYERS

	# Strings to try to communicate obscure behaviours of this rig type in the params UI.
	relinking_behaviour = ""
	parent_switch_behaviour = "The active parent will own the rig's root bone."
	parent_switch_overwrites_root_parent = True
	always_use_custom_props = False

	def find_org_bones(self, pose_bone):
		"""Populate self.bones.org.main."""

		chain = self.get_rigify_chain(pose_bone)
		from rigify.utils.bones import BoneDict
		return BoneDict(main=[b.name for b in chain])

	def initialize(self):
		"""First Rigify stage, called by the Generator.
		https://wiki.blender.org/wiki/Process/Addons/Rigify/RigClass
		"""
		super().initialize()

		from .. import cloud_generator
		assert type(self.generator) == cloud_generator.CloudGenerator, "CloudRig rig type initialized without CloudGenerator. This is a bug!"

		self.bone_count = len(self.bones.org.main)

		### Quick access to the generator's log manager
		self.logger = self.generator.logger

		### Quick access to the generator's name manager
		self.naming = self.generator.naming

		# Determine Suffix/Prefix
		self.side_suffix = ""
		self.side_prefix = ""
		is_left = self.naming.side_is_left(self.base_bone)
		if is_left:
			self.side_suffix = "L"
			self.side_prefix = "Left"
		elif is_left==False:
			self.side_suffix = "R"
			self.side_prefix = "Right"

		self.generator_params = self.generator.metarig.data
		self.defaults = dict(self.generator.defaults)

		self.meta_base_bone = self.generator.metarig.pose.bones.get(self.base_bone.replace("ORG-", ""))

		self.scale = self.generator.scale

		# Reference to the rig's own root bone which should be filled in during create_bone_infos()
		# Used for the "Custom Root Parent" feature.
		self.root_bone = None

		self.force_parameters(self.meta_base_bone, self.params)

		# Prepare Bone Sets
		self.bone_sets = dict()
		self.init_bone_sets()

		# Quick access to the most important bone sets
		self.bones_org = self.bone_sets['Original Bones']
		self.bones_def = self.bone_sets['Deform Bones']
		self.bones_mch = self.bone_sets['Mechanism Bones']

	def force_parameters(self, meta_base_bone, params):
		"""Allows the class to force certain parameter values for its instances."""
		clas = type(self)
		for param in clas.forced_params.keys():
			forced_value = clas.forced_params[param]
			if forced_value != 'NOFORCE':
				meta_base_bone.rigify_parameters[param] = forced_value
				setattr(params, param, forced_value)

	@property
	def properties_bone(self) -> BoneInfo:
		"""Ensure that a Properties bone exists, and return it."""
		# This is a @property so if it's never called, the properties bone is not created.
		# https://en.wikipedia.org/wiki/Lazy_initialization

		if self.params.CR_base_props_storage == 'CUSTOM':
			prop_bone_name = self.params.CR_base_props_storage_bone
			properties_bone = self.generator.find_bone_info(prop_bone_name)
			if properties_bone:
				return properties_bone

			self.add_log("Custom Property bone not found"
				,trouble_bone = prop_bone_name
				,description = f"Custom Property bone named {prop_bone_name} not found, falling back to default Properties bone. If it exists, make sure it generates before this rig."
			)
			self.params.CR_base_props_storage = 'DEFAULT'

		if self.params.CR_base_props_storage == 'DEFAULT':
			bone_name = "Properties"
			properties_bone = self.generator.find_bone_info(bone_name)
			if not properties_bone:
				properties_bone = self.generator.root_set.new(
					name		  = bone_name
					,head		  = Vector((0, self.scale*2, 0))
					,tail		  = Vector((0, self.scale*2, self.scale*2))
					,bbone_width  = 1/8
					,custom_shape = self.ensure_widget("Cogwheel_Y")
					,use_custom_shape_bone_size = True
				)
			return properties_bone
		elif self.params.CR_base_props_storage == 'GENERATED':
			# Create a bone at the base of the rig with a cogwheel shape.
			properties_bone = self.generate_properties_bone()
			# This block should only run once, so change the storage type to no longer be 'GENERATED'.
			self.params.CR_base_props_storage = 'CUSTOM'
			self.params.CR_base_props_storage_bone = properties_bone.name
			return properties_bone

	def generate_properties_bone(self) -> BoneInfo:
		org_bone = self.bones_org[0]
		properties_bone = self.bones_mch.new(
			name		  = org_bone.name.replace("ORG", "PRP")
			,source 	  = org_bone
			,parent		  = org_bone
			,custom_shape = self.ensure_widget("Cogwheel_Y")
			,use_custom_shape_bone_size = True
		)
		properties_bone.layers = self.meta_base_bone.bone.layers[:]
		return properties_bone

	def prepare_bones(self):
		"""Second Rigify stage, called by the generator.
		https://wiki.blender.org/wiki/Process/Addons/Rigify/RigClass
		"""
		self.create_bone_infos()
		skip_root_parenting = self.parent_switch_overwrites_root_parent and self.params.CR_base_parent_switching
		if not skip_root_parenting and self.params.CR_base_parent != "":
			self.apply_custom_root_parent()
		if self.params.CR_base_parent_switching:
			self.apply_parent_switching(self.params.CR_base_parent_slots)
		self.relink()

	def create_bone_infos(self):
		"""Create the BoneInfo instances which will be turned into real bones by 
		the CloudRig generator."""
		self.load_org_bone_infos()
		self.root_bone = self.bones_org[0]

	def relink(self):
		# Relink the base bone.
		bi = self.root_bone
		bi.relink()

	def load_org_bone_infos(self):
		"""Read ORG bones into BoneInfo instances in self.bones_org."""

		for bn in self.bones.org.main:
			eb = self.get_bone(bn)
			eb.use_connect = False

			meta_org_name = eb.name[4:]
			meta_org = self.generator.metarig.pose.bones.get(meta_org_name)

			if self.naming.has_trailing_zeroes(meta_org):
				self.add_log("Trailing zeroes"
					,trouble_bone = eb.name
					,operator = 'object.cloudrig_rename_bone'
					,op_kwargs = {'old_name' : meta_org_name}
				)

			org_bi = self.bones_org.new_from_real(self.obj, eb)
			org_bi.layers = self.bones_org.layers[:]
			org_bi.bbone_width = eb.bbone_x / self.scale
			if eb.parent:
				parent = self.generator.find_bone_info(eb.parent.name)
				org_bi.parent = parent

			# TODO: arbitrary property assignment, should be avoided!
			org_bi.meta_bone = meta_org

	def add_log(self
			,description_short
			,**kwargs
		):
		kwargs['owner_bone'] = self.meta_base_bone.name
		self.generator.logger.log(description_short ,**kwargs)

	def add_log_bug(self
			,description_short
			,**kwargs
		):
		kwargs['owner_bone'] = self.meta_base_bone.name
		self.generator.logger.log_bug(description_short ,**kwargs)

	# TODO these functions probably belong to the generator and should be called get_ instead of find_.
	def find_symmetry_rig(self) -> BaseRig:
		"""Find another rig in the generator with the opposite name for self.base_bone."""
		flipped_name = self.naming.flipped_name(self.base_bone)
		if flipped_name == self.base_bone: return

		for rig in self.generator.rig_list:
			if rig.base_bone == flipped_name:
				return rig

	def find_sibling_rigs(self) -> List[BaseRig]:
		siblings = []
		for rig in self.generator.rig_list:
			if rig.rigify_parent == self.rigify_parent:
				siblings.append(rig)

		return siblings

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_base_props_storage = EnumProperty(
			name		 = "Custom Property Storage"
			,items		 = [
				('DEFAULT', "Shared", 'Use a shared bone called "Properties"')
				,('CUSTOM', "Picked", "Select an existing bone")
				,('GENERATED', "Generated", 'Generate a bone specifically for this rig element, prefixed "PRP-"')
			]
			,description = "Where to store the custom properties needed for this rig element"
		)
		params.CR_base_props_storage_bone = StringProperty(
			name		 = "Properties Bone"
			,description = 'Store custom properties in the chosen bone. If empty, will fall back to a bone called "Properties"'
			,default	 = ""
		)

		cls.add_parent_switch_parameters(params)
		cls.add_bone_set_parameters(params)

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)

		cls.define_bone_set(params, 'Deform Bones',		default_layers=[cls.DEFAULT_LAYERS.DEF], is_advanced=True)
		cls.define_bone_set(params, 'Mechanism Bones',	default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)
		cls.define_bone_set(params, 'Original Bones',	default_layers=[cls.DEFAULT_LAYERS.ORG], is_advanced=True)

	@classmethod
	def is_bone_set_used(cls, params, set_info):
		if set_info['is_advanced']:
			return params.CR_show_advanced_bone_sets
		return True

	@classmethod
	def parameters_ui(cls, layout, params):
		"""This function from the Rigify API is not used, because we 
		organize all CloudRig rig type parameters into sub-panels,
		registered in ui_rig_types.py.
		"""
		pass

	@classmethod
	def is_using_custom_props(cls, context, params):
		"""Determine whether the custom property storage UI should be drawn or not."""
		# TODO: Instead of an awkward "feature exists or not" flag like this, 
		# we should split these features off into a compositable class, 
		# eg. utils.custom_properties->CloudCustomPropertyMixin.
		if cls.always_use_custom_props:
			return True
		return False

	@classmethod
	def draw_custom_prop_params(cls, layout, context, params):
		metarig = context.object
		rig = metarig.data.rigify_target_rig

		cls.draw_prop(layout, params, "CR_base_props_storage", expand=True)
		if params.CR_base_props_storage == 'CUSTOM':
			cls.draw_prop_search(layout, params, 'CR_base_props_storage_bone', rig.pose, 'bones')
		return layout
