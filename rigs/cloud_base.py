import bpy
from typing import Dict, List

from bpy.props import BoolProperty, StringProperty, BoolVectorProperty
from mathutils import Vector
from collections import OrderedDict
from enum import Enum

from ..bone import BoneSet
from .cloud_utils import CloudUtilities
from ..ui import ui_label_with_linebreak, dropdown_ui
from ..cloudrig import draw_layers_ui
from ..utils.naming import CloudNameManager, name_side_is_left
from ..utils.object import CloudObjectUtilitiesMixin

from rigify.base_rig import BaseRig

class DefaultLayers(Enum):
	IK_MAIN = 0
	IK_SECOND = 16
	FK_MAIN = 1
	STRETCH = 2

	DEF = 29
	MCH = 30
	ORG = 31

	FACE_MAIN = 3
	FACE_SECOND = 19
	FACE_TWEAK = 20

class CloudBaseRig(BaseRig, CloudUtilities, CloudObjectUtilitiesMixin):
	"""Base for all CloudRig rigs. Does nothing on its own."""

	ui_rows: Dict[str, bpy.types.UILayout] = {}	# Keep track of certain UI rows so they can be modified later.

	bone_set_defs: Dict[str, str] = OrderedDict()

	default_layers = lambda name: DefaultLayers[name].value

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

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
			self.side_suffix = "Right"

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

	def find_org_bones(self, pose_bone):
		"""Populate self.bones.org.main with a continuous connected bone chain
			where none of the chain elements have a rigify type."""

		cur_pb = pose_bone
		chain = [cur_pb.name]
		while cur_pb and len(cur_pb.children)>0:
			next_bone = None
			for c in cur_pb.children:
				if c.rigify_type=="" and c.bone.use_connect:
					if next_bone != None:
						print(f"""Warning: Branching connected bone chain for {pose_bone.name}: \n
						\tChain could continue with either {next_bone.name} or {c.name}. \n
						\tPicking the first one arbitrarily! \n
						\tDisconnect the bone or assign a rigify type to make it unambiguous.""")
					else:
						next_bone = c
			if next_bone:
				chain.append(next_bone.name)
			cur_pb = next_bone

		from rigify.utils.bones import BoneDict
		return BoneDict(main=chain)

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		from .. import cloud_generator
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
	def ikfk_properties_bone(self):
		""" Ensure that a Properties bone exists, and return it. """
		# This is a @property so that if it's never called(like in the case of very simple rigs), the properties bone is not created.
		bone_name = "Properties_IKFK"
		ikfk_properties_bone = self.get_bone_info(bone_name)
		if not ikfk_properties_bone:
			ikfk_properties_bone = self.generator.root_set.new(
				name		  = "Properties_IKFK"
				,head		  = Vector((0, self.scale*2, 0))
				,tail		  = Vector((0, self.scale*4, 0))
				,bbone_width  = 1/8
				,custom_shape = self.load_widget("Cogwheel")
				,use_custom_shape_bone_size = True
			)
		return ikfk_properties_bone

	def ensure_bone_set(self, bone_set_name):
		"""Take a bone set definition stored in the class and create a real BoneSet object for it on self."""
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
		# Load ORG bones into BoneInfo instances in self.org_chain.

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
			# Remove constraints from the ORG bone and load them into the BoneInfo so they can be read and modified.
			pb = self.obj.pose.bones.get(eb.name)
			for c in pb.constraints:
				ci = org_bi.add_constraint_from_real(c)
				pb.constraints.remove(c)

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

		assert override in ['', 'DEF', 'MCH', 'ORG'], "Error: Unsupported bone set override"

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
		""" Create parameters for this rig's bone sets. """
		cls.bone_set_defs = OrderedDict()
		params.CR_show_bone_sets = BoolProperty(name="Bone Sets")

		cls.define_bone_set(params, "Original Bones",			 default_layers=[cls.default_layers('ORG')], override='ORG')
		cls.define_bone_set(params, "Display Transform Helpers", default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Parent Switch Helpers",	 default_layers=[cls.default_layers('MCH')], override='MCH')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		cls.define_bone_sets(params)

	@classmethod
	def bone_set_ui(cls, params, layout, set_info):
		import bpy
		obj = bpy.context.object
		cloudrig = obj.data.cloudrig_parameters
		if set_info['override'] == 'DEF' and cloudrig.override_def_layers: return
		if set_info['override'] == 'MCH' and cloudrig.override_mch_layers: return
		if set_info['override'] == 'ORG' and cloudrig.override_org_layers: return

		cls.ui_rows[set_info['param']] = col = layout.column()
		col.prop_search(params, set_info['param'], obj.pose, "bone_groups", text=set_info['name'])

		if True:
			layout.use_property_split=False
			draw_layers_ui(layout, obj, show_hidden=cloudrig.show_layers_preview_hidden, owner=params, layers_prop = set_info['layer_param'])
			# TODO: This results in a pretty massive piece of UI. Might be nicer as a UIList, but not sure if possible?
		else:
			row = col.row()
			row.use_property_split=False
			row.prop(params, set_info['layer_param'], text="")
		layout.separator()

	@classmethod
	def bone_sets_ui(cls, layout, params):
		if not cls.cloud_dropdown_ui(layout, params, 'CR_show_bone_sets'): return

		import bpy
		obj = bpy.context.object

		cloudrig = obj.data.cloudrig_parameters
		layout.prop(cloudrig, 'show_layers_preview_hidden')

		for ui_name in cls.bone_set_defs.keys():
			set_info = cls.bone_set_defs[ui_name]
			cls.bone_set_ui(params, layout, set_info)

	@classmethod
	def cloud_dropdown_ui(cls, layout, params, dropdown_param_name):
		layout.separator()
		return dropdown_ui(layout, params, dropdown_param_name)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		doc = cls.__doc__ or cls.__bases__[0].__doc__
		if doc:
			ui_label_with_linebreak(layout, doc)

		layout.use_property_split = True
		layout.use_property_decorate = False
		col = layout.column()
		return col

	@classmethod
	def parameters_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		cls.ui_rows = {}

		layout = cls.cloud_params_ui(layout, params)
		layout.separator()
		cls.bone_sets_ui(layout, params)