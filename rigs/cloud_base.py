import bpy, os
from bpy.props import BoolProperty, FloatProperty, StringProperty, BoolVectorProperty
from mathutils import Vector
from collections import OrderedDict

from rigify.base_rig import BaseRig, stage

from ..definitions.bone import BoneSet
from .cloud_utils import CloudUtilities
from .. import cloud_generator
from enum import Enum

class DefaultLayers(Enum):
	IK_MAIN = 0
	IK_SECOND = 16
	FK_MAIN = 1
	STRETCH = 2

	DEF = 29
	MCH = 30
	ORG = 31

class CloudBaseRig(BaseRig, CloudUtilities):
	"""Base for all CloudRig rigs."""

	description = "CloudRig Element (no description)"

	bone_set_defs = OrderedDict()	# TODO: We could simply store a list of BoneSet instances at the class level, which would then be copied over at the instance level?
	
	default_layers = lambda name: DefaultLayers[name].value

	@property
	def all_bones(self):
		""" Get a list of all bones in this rig, including bones in the generator. """
		all_bones = []

		sets = self.bone_sets[:]
		sets.append(self.generator.root_set)
		if self.generator_params.cloudrig_parameters.double_root:
			sets.append(self.generator.root_parent_set)

		for bone_set in sets:
			for bi in bone_set:
				all_bones.append(bi)

		return all_bones

	def find_org_bones(self, bone):
		"""Populate self.bones.org."""
		from rigify.utils.bones import BoneDict
		from rigify.utils.rig import connected_children_names

		return BoneDict(
			main=[bone.name] + connected_children_names(self.obj, bone.name),
		)

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""
		
		assert type(self.generator) == cloud_generator.CloudGenerator, "Error: CloudRig has wrong Generator type. CloudRig requires its own Generator class - Perhaps you're using bpy.ops.rigify_generate instead of bpy.ops.cloudrig_generate?"

		self.generator_params = self.generator.metarig.data

		self.mch_disable_select = not self.generator_params.cloudrig_parameters.mechanism_selectable
		
		self.meta_base_bone = self.generator.metarig.pose.bones.get(self.base_bone.replace("ORG-", ""))
		self.parent_candidates = {}

		self.scale = self.generator.scale

		# Prepare Bone Sets
		self.bone_sets = []
		self.defaults = dict(self.generator.defaults)
		self.ensure_bone_sets()

		# Determine Suffix/Prefix
		self.side_suffix = ""
		self.side_prefix = ""
		base_bone_name = self.slice_name(self.base_bone)
		if "L" in base_bone_name[2]:
			self.side_suffix = "L"
			self.side_prefix = "Left"
		elif "R" in base_bone_name[2]:
			self.side_suffix = "R"
			self.side_prefix = "Right"

		parent = self.get_bone(self.base_bone).parent
		self.bones.parent = parent.name if parent else ""

		# Get a reference to the Root bone from the generator, and register it as a parent candidate.
		self.root_bone = None
		if self.generator_params.cloudrig_parameters.create_root:
			self.root_bone = self.generator.root_bone
			self.register_parent(self.root_bone, "Root")

		# Clear rig object custom properties.
		for k in self.obj.data.keys():
			if k in ['_RNA_UI', 'rig_id']: continue
			del self.obj.data[k]

	@property
	def prop_bone(self):
		""" Ensure that a Properties bone exists, and return it. """
		# This is a @property so that if it's never called(like in the case of very simple rigs), the properties bone is not created.
		bone_name = "Properties_IKFK"
		prop_bone = self.get_bone_info(bone_name)
		if not prop_bone:
			prop_bone = self.generator.root_set.new(
				name		  = "Properties_IKFK"
				,head		  = Vector((0, self.scale*2, 0))
				,tail		  = Vector((0, self.scale*4, 0))
				,bbone_width  = 1/8
				,custom_shape = self.load_widget("Cogwheel")
				,use_custom_shape_bone_size = True
			)
		return prop_bone

	def ensure_bone_set(self, bone_set_name):
		bone_set_defs = type(self).bone_set_defs

		if bone_set_name not in bone_set_defs:
			print(f"Warning: Bone Set definition named {bone_set_name} not found in class {type(self)}. Could not create Bone Set.")
			return
		
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
			self.generator,
			ui_name = bone_set_def['name'],
			bone_group = getattr(self.params, bone_set_def['param']),
			layers = bone_set_def['layers'],
			preset = bone_set_def['preset'],
			defaults = self.defaults
		)

		self.bone_sets.append(new_set)

		return new_set

	def ensure_bone_sets(self):
		self.org_chain = self.ensure_bone_set("Original Bones")
		self.dsp_bones = self.ensure_bone_set("Display Transform Helpers")
		self.parent_switch_bones = self.ensure_bone_set("Parent Switch Helpers")

	def prepare_bones(self):
		self.load_org_bones()

	def load_org_bones(self):
		# Load ORG bones into BoneInfo instances.
		# self.org_chain = []

		for bn in self.bones.org.main:
			eb = self.get_bone(bn)
			eb.use_connect = False

			meta_org_name = eb.name[4:]
			meta_org = self.generator.metarig.pose.bones.get(meta_org_name)

			org_bi = self.org_chain.new(
				name		 = bn
				,source		 = eb
				,hide_select = self.mch_disable_select
			)

			org_bi.meta_bone = meta_org

	def generate_bones(self):
		self.bone_sets.append(self.generator.root_set)
		try:
			self.bone_sets.append(self.generator.root_parent_set)
		except:
			pass
		# TODO: Move this to generator code, before stage is called.
		for bone_set in self.bone_sets:
			for bi in bone_set:
				if ( 
					bi.name in self.obj.data.edit_bones or
					bi.name in self.bones.flatten() or
					bi.name == 'root'
				):
					# print(f"Warning: Bone {bi.name} already exists, skipping!")
					continue
				self.copy_bone('root', bi.name)

	def parent_bones(self):
		# TODO: Move this to generator code, before stage is called.
		for bone_set in self.bone_sets:
			for bi in bone_set:
				edit_bone = self.get_bone(bi.name)
				bi.write_edit_data(self.obj, edit_bone)

	def configure_bones(self):
		pass

	##############################
	# Parameters

	@classmethod
	def define_bone_set(cls, params, ui_name, default_group="", default_layers=[0], override="", preset=-1):
		""" 
		A bone set is just a set of rig parameters for choosing a bone group and list of bone layers.
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
				description = "Select what group this set of bones should be assigned to"
			)
		)
		
		default_layers_bools = [i in default_layers for i in range(32)]
		setattr(
			params, 
			layer_param_name, 
			BoolVectorProperty(
				size = 32, 
				subtype = 'LAYER', 
				description = "Select what layers this set of bones should be assigned to",
				default = default_layers_bools
			)
		)

		assert override in ['', 'DEF', 'MCH', 'ORG'], "Error: Unsupported bone set override"
		
		cls.bone_set_defs[ui_name] = {
			'name' 		   : ui_name
			,'preset' 	   : preset				# Bone Group color preset to use in case the bone group doesn't already exist.
			,'param' 	   : param_name			# Name of the bone group name parameter
			,'layer_param' : layer_param_name	# Name of the bone layers parameter
			,'override'	   : override
		}
		return ui_name

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		cls.bone_set_defs = OrderedDict()
		params.CR_show_bone_sets = BoolProperty(name="Bone Sets")

		cls.define_bone_set(params, "Original Bones", default_layers=[cls.default_layers('ORG')], override='ORG')
		cls.define_bone_set(params, "Display Transform Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Parent Switch Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		cls.define_bone_sets(params)

	
	@classmethod
	def bone_set_ui(cls, params, layout, set_info, ui_rows):
		cloudrig = bpy.context.object.data.cloudrig_parameters
		if set_info['override'] == 'DEF' and cloudrig.override_def_layers: return
		if set_info['override'] == 'MCH' and cloudrig.override_mch_layers: return
		if set_info['override'] == 'ORG' and cloudrig.override_org_layers: return

		ui_rows[set_info['param']] = col = layout.column()
		col.prop_search(params, set_info['param'], bpy.context.object.pose, "bone_groups", text=set_info['name'])
		col.prop(params, set_info['layer_param'], text="")
		layout.separator()

	@classmethod
	def bone_sets_ui(cls, layout, params, ui_rows):
		icon = 'TRIA_DOWN' if params.CR_show_bone_sets else 'TRIA_RIGHT'
		layout.prop(params, "CR_show_bone_sets", toggle=True, icon=icon)
		if not params.CR_show_bone_sets: return

		for ui_name in cls.bone_set_defs.keys():
			set_info = cls.bone_set_defs[ui_name]
			cls.bone_set_ui(params, layout, set_info, ui_rows)
		
		return ui_rows
	
	@classmethod
	def cloud_params_ui(cls, layout, params):
		ui_rows = {}
		from ..ui import ui_label_with_linebreak
		ui_label_with_linebreak(layout, cls.description)
		return ui_rows

	@classmethod
	def parameters_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		ui_rows = cls.cloud_params_ui(layout, params)
		layout.separator()
		cls.bone_sets_ui(layout, params, ui_rows)

		# We can return a dictionary of key:UILayout elements, in case we want to affect the UI layout of inherited rig elements.
		return ui_rows