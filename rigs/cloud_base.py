# Typing
import bpy
from ..bone import BoneInfo
from typing import Dict, List

# CloudBaseRig parent classes
from rigify.base_rig import BaseRig
from ..bone import BoneSetMixin
from ..utils.ui import CloudUIMixin
from ..utils.mechanism import CloudMechanismMixin
from ..utils.animation import CloudAnimationMixin
from ..utils.object import CloudObjectUtilitiesMixin

# The rest
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector
from enum import Enum
from ..parent_switching import draw_cloudrig_parents

class DefaultLayers(Enum):
	IK_MAIN = 0
	IK_SECOND = 16
	FK_MAIN = 1
	FK_SECOND = 17

	STRETCH = 2

	FACE_MAIN = 3
	FACE_SECOND = 19

	DEF = 29
	MCH = 30
	ORG = 31

	FACE_TWEAK = 20

class CloudBaseRig(
					BaseRig, 
					CloudMechanismMixin, 
					CloudObjectUtilitiesMixin, 
					CloudUIMixin, 
					CloudAnimationMixin,
					BoneSetMixin
	):
	"""Base class that all CloudRig rigs should inherit from."""

	default_layers = lambda name: DefaultLayers[name].value

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		### Quick access to the generator's name manager
		self.naming = self.generator.naming

		### Quick access to the generator's log manager
		self.logger = self.generator.logger

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

	def find_org_bones(self, pose_bone):
		"""Populate self.bones.org.main."""

		chain = self.get_rigify_chain(pose_bone)
		from rigify.utils.bones import BoneDict
		return BoneDict(main=[b.name for b in chain])

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		from .. import cloud_generator
		assert type(self.generator) == cloud_generator.CloudGenerator, "CloudRig has wrong Generator type. CloudRig requires its own Generator class - You're probably using bpy.ops.rigify_generate instead of bpy.ops.cloudrig_generate. Perhaps the Generate button is not being replaced even though it should?"

		self.generator_params = self.generator.metarig.data

		self.mch_disable_select = not self.generator_params.cloudrig_parameters.mechanism_selectable

		self.meta_base_bone = self.generator.metarig.pose.bones.get(self.base_bone.replace("ORG-", ""))
		self.parent_candidates = {}

		self.scale = self.generator.scale

		# Prepare Bone Sets
		self.bone_sets = []	# TODO: This is currently not used, but it may be turned into a dictionary in future.
		self.defaults = dict(self.generator.defaults)
		self.ensure_bone_sets()

		parent = self.get_bone(self.base_bone).parent
		self.bones.parent = parent.name if parent else ""

		# Get a reference to the Root bone from the generator, and register it as a parent candidate.
		# TODO: It's a bit awkward that every rig registers the root bone as a parent candidate. 
		# Instead, the root bone could be hardcoded into get_parent_candidates().
		self.root_bone = None
		if self.generator_params.cloudrig_parameters.create_root:
			self.root_bone = self.generator.root_bone
			self.register_parent(self.root_bone, "Root")

		# Clear rig object custom properties.
		# TODO: Why is this not in the generator code???
		for k in self.obj.data.keys():
			if k in ['_RNA_UI', 'rig_id']: continue
			del self.obj.data[k]
		
		self.update_forced_params()

	def update_forced_params(self):
		clas = type(self)
		for param in clas.forced_params.keys():
			forced_value = clas.forced_params[param]
			if forced_value != 'NOFORCE':
				self.meta_base_bone.rigify_parameters[param] = forced_value
				setattr(self.params, param, forced_value)

	@property
	def properties_bone(self):
		"""Ensure that a Properties bone exists, and return it."""
		# This is a @property so that if it's never called(like in the case of very simple rigs), the properties bone is not created.
		bone_name = "Properties"
		properties_bone = self.get_bone_info(bone_name)
		if not properties_bone:
			properties_bone = self.generator.root_set.new(
				name		  = bone_name
				,head		  = Vector((0, self.scale*2, 0))
				,tail		  = Vector((0, self.scale*4, 0))
				,bbone_width  = 1/8
				,custom_shape = self.ensure_widget("Cogwheel")
				,use_custom_shape_bone_size = True
			)
		return properties_bone

	def ensure_bone_sets(self):
		self.org_chain = self.ensure_bone_set("Original Bones")
		self.dsp_bones = self.ensure_bone_set("Display Transform Helpers")
		self.parent_switch_bones = self.ensure_bone_set("Parent Switch Helpers")
		self.def_chain = self.ensure_bone_set("Deform Bones")

	def prepare_bones(self):
		self.create_bone_infos()
		if self.params.CR_base_parent!="":
			self.apply_custom_parent()
		if self.params.CR_base_relink:
			self.relink()

	def create_bone_infos(self):
		self.load_org_bone_infos()

	def apply_custom_parent(self, bone=None, parent_name=""):
		if not bone:
			bone = self.org_chain[0]
		if parent_name=="":
			parent_name = self.params.CR_base_parent
		self.bendy_parenting(bone, parent_name)

	def relink(self):
		bi = self.org_chain[0]
		# Relink bone drivers
		for d in bi.drivers:
			self.relink_driver(d)

		for c in bi.constraint_infos:
			c.relink()
			# Relink constraint drivers
			for d in c.drivers:
				self.relink_driver(d)

	def reparent_bone(self, child: BoneInfo):
		"""Overriding from CloudMechanismMixin just for an extra sanity check."""
		parent = super().reparent_bone(child)

		assert parent in self.org_chain, f"Cannot reparent {child}, its parent, {child.parent} was expected to be an ORG bone of rig {self.base_bone}"
		return parent

	def load_org_bone_infos(self):
		"""Read ORG bones into BoneInfo instances in self.org_chain."""

		for bn in self.bones.org.main:
			eb = self.get_bone(bn)
			eb.use_connect = False

			meta_org_name = eb.name[4:]
			meta_org = self.generator.metarig.pose.bones.get(meta_org_name)

			if self.naming.has_trailing_zeroes(meta_org):
				self.add_log("Trailing Zeroes!"
					,trouble_bone = eb.name
					,operator = 'object.cloudrig_rename_bone'
					,op_kwargs = {'old_name' : meta_org_name}
				)

			org_bi = self.org_chain.new_from_real(self.obj, eb)
			org_bi.layers = self.org_chain.layers[:]
			org_bi.hide_select = self.mch_disable_select
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
		
		params.CR_base_show_settings = BoolProperty(
			name		 = "Base Settings"
			,description = "Reveal settings for the cloud_base rig type"
		)
		params.CR_base_parent_switching = BoolProperty(
			name = "Parent Switching"
			,description = "Use parent switching mechanism for the root of this rig"
		)
		params.CR_base_relink = BoolProperty(
			name		 = "Relink Constraints"
			,description = "Constraints and drivers on this rig will be relinked to the corresponding primary controls that are created for each bone. This can be different for each rig type. For more info, right click and Open Manual"
			,default	 = True
		)
		params.CR_base_parent = StringProperty(
			name		 = "Parent"
			,description = "If specified, parent this rig to the chosen bone. This bone should be a part of a parent rig"
			,default	 = ""
		)

		cls.define_bone_sets(params)

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		params.CR_show_bone_sets = BoolProperty(name="Bone Sets")

		cls.define_bone_set(params, "Original Bones",			 default_layers=[cls.default_layers('ORG')], override='ORG')
		cls.define_bone_set(params, "Display Transform Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Parent Switch Helpers",	 default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Deform Bones",				 default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def parameters_ui(cls, layout, params):
		"""Create the ui for the rig parameters."""

		layout = cls.draw_cloud_params(layout, bpy.context, params)
		layout.separator()
		cls.draw_bone_sets_params(layout, params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_base_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_base_relink")

		cls.draw_prop(layout, params, "CR_base_parent_switching")
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		if rig:
			if params.CR_base_parent_switching:
				draw_cloudrig_parents(layout, context.active_pose_bone.bone)
			else:
				row = layout.row()
				parent_bone = rig.pose.bones.get(params.CR_base_parent)
				if params.CR_base_parent!="" and not parent_bone:
					row.prop_search(params, 'CR_base_parent', rig.pose, 'bones', icon='ERROR')
					row.label(text="Bone no longer exists in rig!")
				else:
					row.prop_search(params, 'CR_base_parent', rig.pose, 'bones')
				if parent_bone and parent_bone.bone.bbone_segments > 1:
					split=layout.row().split(factor=0.4)
					split.row()
					split.label(text="Bendy Bone, will use Armature Constraint")
		else:
			row = layout.row()
			row.prop(params, 'CR_base_parent')
			row.label(text="Generate the rig to pick a custom parent.")

		return layout