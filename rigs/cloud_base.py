# Typing
import bpy
from ..bone import BoneInfo
from typing import List

# CloudBaseRig parent classes
from rigify.base_rig import BaseRig
from ..bone_set import BoneSetMixin
from ..utils.ui import CloudUIMixin
from ..utils.mechanism import CloudMechanismMixin
from ..utils.animation import CloudAnimationMixin
from ..utils.object import CloudObjectUtilitiesMixin

# The rest
from bpy.props import BoolProperty, StringProperty, CollectionProperty, IntProperty, EnumProperty
from mathutils import Vector

from ..parent_switching import draw_cloudrig_parents, ParentSlot
from ..utils.ui import draw_label_with_linebreak

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
					CloudMechanismMixin,
					CloudObjectUtilitiesMixin,
					CloudUIMixin,
					CloudAnimationMixin,
					BoneSetMixin
	):
	"""Base class that all CloudRig rigs should inherit from."""

	DEFAULT_LAYERS = DEFAULT_LAYERS

	# Strings to try to communicate obscure behaviours of this rig type in the params UI.
	use_custom_props = False	# TODO: Instead of an awkward "feature exists or not" flag like this, we should split these features off into a compositable class, eg. utils.custom_properties->CloudCustomPropertyMixin.
	custom_prop_behaviour = "Store Custom Properties for this rig element in a cogwheel shaped bone at the base of the rig."
	relinking_behaviour = ""
	parent_switch_behaviour = "The active parent will own the rig's root bone."
	parent_switch_overwrites_root_parent = True

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

		self.scale = self.generator.scale

		# Prepare Bone Sets
		self.bone_sets = dict()
		self.defaults = dict(self.generator.defaults)
		self.ensure_bone_sets()

		parent = self.get_bone(self.base_bone).parent
		self.bones.parent = parent.name if parent else ""

		# Reference to the rig's own root bone which should be filled in during create_bone_infos()
		# Used for the "Custom Root Parent" feature.
		self.root_bone = None

		self.update_forced_params()

	def update_forced_params(self):
		clas = type(self)
		for param in clas.forced_params.keys():
			forced_value = clas.forced_params[param]
			if forced_value != 'NOFORCE':
				self.meta_base_bone.rigify_parameters[param] = forced_value
				setattr(self.params, param, forced_value)

	@property
	def properties_bone(self) -> BoneInfo:
		"""Ensure that a Properties bone exists, and return it."""
		# This is a @property so that if it's never called(like in the case of very simple rigs), the properties bone is not created.
		# https://en.wikipedia.org/wiki/Lazy_initialization

		if self.params.CR_base_props_storage == 'CUSTOM':
			prop_bone_name = self.params.CR_base_props_storage_bone
			properties_bone = self.generator.find_bone_info(prop_bone_name)
			if not properties_bone:
				self.add_log("Custom Property bone not found"
					,trouble_bone = prop_bone_name
					,description = f"Custom Property bone named {prop_bone_name} not found, falling back to default Properties bone. If it exists, make sure it generates before this rig."
				)
				self.params.CR_base_props_storage = 'DEFAULT'
			else:
				return properties_bone

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
		org_bone = self.bone_sets['Original Bones'][0]
		properties_bone = self.bone_sets['Mechanism Bones'].new(
			name		  = org_bone.name.replace("ORG", "PRP")
			,source 	  = org_bone
			,parent		  = org_bone
			,custom_shape = self.ensure_widget("Cogwheel_Y")
			,use_custom_shape_bone_size = True
		)
		properties_bone.layers = self.meta_base_bone.bone.layers[:]
		return properties_bone

	def prepare_bones(self):
		self.create_bone_infos()
		skip_root_parenting = self.parent_switch_overwrites_root_parent and self.params.CR_base_parent_switching
		if not skip_root_parenting and self.params.CR_base_parent != "":
			self.apply_custom_root_parent()
		if self.params.CR_base_parent_switching:
			self.apply_parent_switching(self.params.CR_base_parent_slots)
		if self.params.CR_base_relink:
			self.relink()

	def create_bone_infos(self):
		self.load_org_bone_infos()
		self.root_bone = self.bone_sets['Original Bones'][0]

	def apply_parent_switching(self, parent_slots,
			child_bone=None,
			prop_bone=None, prop_name="",
			ui_area="misc_settings", row_name="", col_name=""
		):
		"""Rig a bone with multiple switchable parents, using Armature constraint and drivers."""
		if not child_bone:
			child_bone = self.root_bone
		if not prop_bone:
			prop_bone = self.properties_bone
		if prop_name=="":
			prop_name="parents_"+child_bone.name
		if row_name=="":
			row_name = child_bone.name.split(".")[0]
		if col_name=="":
			col_name = child_bone.name

		# Create parent bone that will hold the Armature constraint.
		arm_con_bone = self.create_parent_bone(child_bone, self.bone_sets['Mechanism Bones'])
		arm_con_bone.hide_select = self.mch_disable_select
		arm_con_bone.name = "P-" + child_bone.name
		arm_con_bone.custom_shape = None

		parent_ui_names, parent_bone_names = self.sanitize_parent_list(parent_slots)
		if not parent_ui_names:
			return

		targets = [{'subtarget' : bone_name} for bone_name in parent_bone_names]

		# Create custom property
		info = {
			"prop_bone" : prop_bone,
			"prop_id" : prop_name,
			"texts" : parent_ui_names,

			"operator" : "pose.cloudrig_switch_parent_bake",
			"icon" : "COLLAPSEMENU",
			"parent_names" : parent_ui_names,
			"bones" : [child_bone.name],
			}
		self.add_ui_data(ui_area, row_name, col_name, info, default=0, max=len(parent_ui_names)-1)

		# Add armature constraint
		arm_con = arm_con_bone.add_constraint('ARMATURE',
			targets = targets
		)

		# Add weight drivers
		for i, t in enumerate(arm_con.targets):
			arm_con.drivers.append({
				'prop' : f'targets[{i}].weight',
				'expression' : f'parent=={i}',
				'variables' : {
					'parent' : {
						'type' : 'SINGLE_PROP',
						'targets' : [{
							'data_path' : f'pose.bones["{prop_bone.name}"]["{prop_name}"]'
						}]
					}
				}
			})

	def sanitize_parent_list(self, parent_slots: List[ParentSlot]) -> (List[str], List[str]):
		"""Gather parent information and check for issues.

		Returns two lists of equal length, first one is the UI name second is the bone name of each parent.
		"""

		parent_bone_names = []
		parent_ui_names = []

		for i, ps in enumerate(parent_slots):
			if ps.bone == "":
				self.add_log(
					"Parent not found"
					,description=f"Parent slot #{i}: {ps.bone} not specified, skipping."
				)
				continue
			if ps.name == "":
				self.add_log(
					"Nameless parent"
					,description = f"Parent slot #{i}: {ps.bone} has no UI name, falling back to the bone's name."
				)
				parent_ui_names.append(ps.bone)
			else:
				parent_ui_names.append(ps.name)
			parent_bone_names.append(ps.bone)

		if len(parent_ui_names) == 0:
			self.add_log("No parents found"
				,description = f"No parents specified for parent switching setup, skipping completely."
			)
			return [], []

		# Force the Root to be an available parent for all parent switching setups
		# TODO: This should be removed after Sprite Fright!
		if self.generator_params.cloudrig_parameters.create_root and 'root' not in parent_bone_names:
			parent_ui_names.insert(0, "Root")
			parent_bone_names.insert(0, 'root')

		return parent_ui_names, parent_bone_names

	def apply_custom_root_parent(self, bone=None, parent_name=""):
		if not bone:
			bone = self.root_bone
		if parent_name == "":
			parent_name = self.params.CR_base_parent

		self.bendy_parenting(bone, parent_name)

	def relink(self):
		# Relink the base bone.
		bi = self.root_bone
		bi.relink()

	def load_org_bone_infos(self):
		"""Read ORG bones into BoneInfo instances in self.bone_sets['Original Bones']."""

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

			org_bi = self.bone_sets['Original Bones'].new_from_real(self.obj, eb)
			org_bi.layers = self.bone_sets['Original Bones'].layers[:]
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
			name		 = "Parent Switching"
			,description = "Use parent switching for this rig. Different rig types may implement this differently. A rig-type-specific explanation is shown below when enabled"
			,default	 = False
		)
		params.CR_base_relink = BoolProperty(
			name		 = "Relink Constraints"
			,description = "Metarig constraints can specify a target bone name after an \"@\" symbol in the constraint name. Constraints and drivers on this rig will be moved to the primary controls generated for each bone. These can be different for each rig type"
			,default	 = True
		)
		params.CR_base_parent = StringProperty(
			name		 = "Root Parent"
			,description = "If specified, parent the root of this rig to the chosen bone"
			,default	 = ""
		)

		params.CR_base_props_storage = EnumProperty(
			name		 = "Custom Property Storage"
			,items		 = [
				('DEFAULT', "Default", 'Use a shared bone called "Properties"')
				,('CUSTOM', "Custom", "Select an existing bone")
				,('GENERATED', "Generated", "Generate a bone specifically for this rig element. This can be implemented differently by different rig types")
			]
		)
		params.CR_base_props_storage_bone = StringProperty(
			name		 = "Properties Bone"
			,description = 'Store custom properties in the chosen bone. If empty, will fall back to a bone called "Properties"'
			,default	 = ""
		)
		params.CR_base_active_parent_slot_index = IntProperty()

		# BUG: Currently this causes an error when turning the Rigify addon off and back on, unless running Reload Scripts in between.
		# It appears as though the error is caused by the ParentSlot class not being registered.
		# So, I tried ensuring that it is registered, but no difference.
		# So, could be an issue with the RigifyParameterValidator class, but I looked at that too and didn't see anything wrong.
		# So, could be a bug in Blender, but then how come other addons that use CollectionProperties don't have this issue?
		params.CR_base_parent_slots = CollectionProperty(type=ParentSlot)

		cls.add_bone_set_parameters(params)

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		params.CR_show_bone_sets = BoolProperty(name="Bone Sets", description="Reveal Bone Set settings")
		params.CR_show_advanced_bone_sets = BoolProperty(name="Advanced Bone Sets", description="Reveal bone sets of helper bones")
		params.CR_active_bone_set_index = IntProperty()

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
		"""Create the ui for the rig parameters."""
		context = bpy.context	# TODO: Rigify should pass context to parameters_ui.

		layout = cls.draw_cloud_params(layout, context, params)
		layout.separator()
		cls.draw_bone_sets_list(layout, context, params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_base_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_base_relink")
		if params.CR_base_relink:
			draw_label_with_linebreak(layout, cls.relinking_behaviour, align_split=True)

		metarig = context.object
		rig = metarig.data.rigify_target_rig

		if not rig:
			draw_label_with_linebreak(layout, "Generate the rig to see parenting parameters.", align_split=True)
			return layout

		layout.separator()
		parent_bone = rig.pose.bones.get(params.CR_base_parent)
		cls.draw_prop(layout, params, "CR_base_parent_switching")
		if params.CR_base_parent!="" and not parent_bone:
			cls.draw_prop_search(layout, params, 'CR_base_parent', rig.pose, 'bones', icon='ERROR')
			draw_label_with_linebreak(layout, "Bone no longer exists in rig!", align_split=True)
		elif not (cls.parent_switch_overwrites_root_parent and params.CR_base_parent_switching):
			cls.draw_prop_search(layout, params, 'CR_base_parent', rig.pose, 'bones')
			if parent_bone and parent_bone.bone.bbone_segments > 1:
				draw_label_with_linebreak(layout, "Bendy Bone, will use Armature Constraint and create a parent helper bone!", align_split=True)

		if params.CR_base_parent_switching:
			draw_label_with_linebreak(layout, cls.parent_switch_behaviour, align_split=True)
			draw_cloudrig_parents(layout, context)

		if cls.use_custom_props:
			layout.separator()
			cls.draw_custom_prop_params(layout, context, params)

		return layout

	@classmethod
	def draw_custom_prop_params(cls, layout, context, params):
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		cls.draw_prop(layout, params, "CR_base_props_storage", expand=True)
		if params.CR_base_props_storage == 'CUSTOM':
			cls.draw_prop_search(layout, params, 'CR_base_props_storage_bone', rig.pose, 'bones')
		elif params.CR_base_props_storage == 'GENERATED':
			draw_label_with_linebreak(layout, cls.custom_prop_behaviour, align_split=True)