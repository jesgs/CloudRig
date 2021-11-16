# Typing
import bpy
from typing import Dict

# CloudBaseRig parent classes
from ..generation.troubleshooting import LoggerMixin
from rigify.base_rig import BaseRig
from ..rig_features.bone_set import BoneSetMixin
from ..rig_features.bone_gizmos import BoneGizmoMixin
from ..rig_features.ui import CloudUIMixin
from ..rig_features.mechanism import CloudMechanismMixin
from ..rig_features.object import CloudObjectUtilitiesMixin
from ..rig_features.parent_switching import CloudParentSwitchMixin
from ..rig_features.custom_properties import CloudCustomPropertiesMixin

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
					LoggerMixin,
					BaseRig,
					CloudParentSwitchMixin,
					CloudMechanismMixin,
					CloudObjectUtilitiesMixin,
					CloudCustomPropertiesMixin,
					CloudUIMixin,
					BoneSetMixin,
					BoneGizmoMixin,
	):
	"""Base class that all CloudRig rigs should inherit from."""

	DEFAULT_LAYERS = DEFAULT_LAYERS

	# Strings to try to communicate obscure behaviours of this rig type in the params UI.
	relinking_behaviour = ""
	parent_switch_behaviour = "The active parent will own the rig's root bone."
	parent_switch_overwrites_root_parent = True

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
		self.add_gizmo_interactions()

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
					,description = "Trailing zeroes in the metarig can cause bone name clashes and should be avoided."
					,operator = 'object.cloudrig_rename_bone'
					,op_kwargs = {'old_name' : meta_org_name}
				)
			if self.naming.has_wrong_separator(meta_org):
				self.raise_error("Wrong separator"
					,trouble_bone = eb.name
					,description = "CloudRig requires the side indicator in the bone's name to be separated by a period(`.`)."
					,operator = 'object.cloudrig_rename_bone'
					,op_kwargs = {'old_name' : meta_org_name}
				)
			if not self.naming.side_is_suffix(meta_org):
				self.raise_error("Side indicator must be suffix"
					,trouble_bone = eb.name
					,description = "CloudRig requires the side indicator in the bone's name to be at the end of the bone name."
					,operator = 'object.cloudrig_rename_bone'
					,op_kwargs = {'old_name' : meta_org_name}
				)

			org_bi = self.bones_org.new_from_real(self.obj, eb)
			org_bi.layers = self.bones_org.layers[:]
			org_bi.bbone_width = eb.bbone_x / self.scale
			if eb.parent:
				parent = self.generator.find_bone_info(eb.parent.name)
				org_bi.parent = parent

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		cls.add_custom_property_parameters(params)
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
	def parameters_ui(cls, layout, params):
		"""This function from the Rigify API is not used, because we
		organize all CloudRig rig type parameters into sub-panels,
		registered in ui_rig_types.py.
		"""
		pass

