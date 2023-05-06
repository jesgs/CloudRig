from typing import Dict

import bpy
from bpy.props import StringProperty, BoolVectorProperty, BoolProperty, IntProperty
from bpy.types import PropertyGroup, UIList, UI_UL_list
from rna_prop_ui import rna_idprop_has_properties

from mathutils import Vector, Matrix
from collections import OrderedDict

from ..utils.misc import find_rig_class
from ..utils.generic_ui_list import draw_ui_list
from ..generation.cloudrig import draw_layers_ui
from .bone import BoneInfo, pose_bone_properties, edit_bone_properties, bone_properties

def driver_from_real(fcurve: bpy.types.FCurve) -> dict:
	driver = fcurve.driver
	"""Return a dictionary describing the driver."""
	driver_info = {
		'type' : driver.type
		,'variables' : []
		,'index' : fcurve.array_index
	}
	if driver.type=='SCRIPTED':
		driver_info['expression'] = driver.expression
	for var in driver.variables:
		driver_info['variables'].append({
			'name' : var.name
			,'type' : var.type
			,'targets' : []
		})
		for t in var.targets:
			target_info = {
				'id' : t.id
			}
			if var.type == 'SINGLE_PROP':
				target_info['id_type'] = t.id_type
				target_info['data_path'] = t.data_path
			else:
				target_info['bone_target'] = t.bone_target
				target_info['transform_type'] = t.transform_type
				target_info['transform_space'] = t.transform_space
				target_info['rotation_mode'] = t.rotation_mode
			driver_info['variables'][-1]['targets'].append(target_info)
	return driver_info

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
		Also responsible for bone group layer assignment.
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

	def __init__(self, rig, ui_name="Bone Set",
			bone_group="Group", normal=None, select=None, active=None, preset=-1,
			layers = [l==0 for l in range(32)],
			defaults = {}
		):
		super().__init__()

		self.rig = rig

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
			if bi.name == name:
				return bi
		return None

	def __repr__(self):
		return f"{self.ui_name}: {super().__repr__()}"

	def new(self, name="Bone", source=None, **kwargs):
		"""Create and add a new BoneInfo to self."""

		generator = self.rig
		if hasattr(self.rig, 'generator'):
			generator = self.rig.generator

		# If a BoneInfo with the passed name already exists, add a warning and do not create a new one.
		bone_info = generator.find_bone_info(name)
		if bone_info:
			generator.logger.log_error("Re-defined bone!"
				,owner_bone   = bone_info.bone_set.rig.meta_base_bone.name
				,trouble_bone = bone_info.name
				,description  = f'Bone name "{bone_info.name}" was used twice! Make sure your bone names are unique and do not have trailing zeroes!'
				,clear_logs	  = False
			)

		if 'bone_group' not in kwargs:
			kwargs['bone_group'] = self.bone_group
		if 'layers' not in kwargs:
			kwargs['layers'] = self.layers
		for key in self.defaults.keys():
			if key not in kwargs:
				kwargs[key] = self.defaults[key]

		bone_info = BoneInfo(self, name, source, **kwargs)
		self.append(bone_info)
		generator.bone_infos.append(bone_info)
		bone_info.owner_rig = self.rig

		return bone_info

	def new_from_real(self, rig: bpy.types.Object, edit_bone: bpy.types.EditBone):
		"""Load a bpy bone into a BoneInfo class along with its constraints, drivers, custom properties."""
		# NOTE: Parenting should be done outside of this function. (TODO but maybe shouldn't need to be?)

		pose_bone = rig.pose.bones.get(edit_bone.name)
		data_bone = pose_bone.bone
		bone_info = self.new(name=edit_bone.name)

		sources = {
			pose_bone : pose_bone_properties
			,data_bone : bone_properties
			,edit_bone : edit_bone_properties
		}

		for bone in sources:
			prop_list = sources[bone]
			for key in prop_list:
				value = getattr(bone, key)
				if value in [None, ""]: continue
				if key == 'bone_group':
					value = value.name
				if type(value) in [Vector, Matrix]:
					value = value.copy()
				setattr(bone_info, key, value)

		#HACK: force use_deform to False for now...
		bone_info.use_deform = False

		# Remove constraints from the bone and load them into the BoneInfo so they can be read and modified.
		for c in pose_bone.constraints:
			ci = bone_info.add_constraint_from_real(c)
			pose_bone.constraints.remove(c)

		# Load drivers
		if rig.animation_data:
			driver_map = self.rig.generator.driver_map
			if bone_info.name in driver_map:
				for data_path, array_index in driver_map[bone_info.name]:
					fcurve = rig.animation_data.drivers.find(data_path, index=array_index)
					driver = fcurve.driver
					path_from_last = "." + data_path.split('"].')[-1]
					if path_from_last.endswith('"]'):
						path_from_last = "[" + path_from_last.split("][")[-1]
					driver_info = driver_from_real(fcurve)
					driver_info['prop'] = path_from_last
					if 'constraints' in fcurve.data_path:
						con_name = data_path.split('constraints["')[-1].split('"]')[0]
						constraint_info = bone_info.get_constraint(con_name)
						if constraint_info:
							constraint_info.drivers.append(driver_info)
					else:
						bone_info.drivers.append(driver_info)
					rig.animation_data.drivers.remove(fcurve)

		# Load custom property definition dictionaries
		if rna_idprop_has_properties(pose_bone):
			rna_properties = {prop.identifier for prop in pose_bone.bl_rna.properties if prop.is_runtime}
			for prop_name in pose_bone.keys():
				if prop_name in rna_properties:
					# We don't want to reset addon-defined properties.
					continue
				if prop_name[0] in "_$": continue
				try:
					prop_data = pose_bone.id_properties_ui(prop_name).as_dict()
				except TypeError:
					# This should only happen with python dictionaries, let's just ignore them for now.
					prop_data = {'default': pose_bone[prop_name]}

				value = pose_bone[prop_name]
				if hasattr(value, 'to_list'):
					value = value.to_list()
					prop_data['default'] = value
				elif hasattr(value, 'to_dict'):
					value = value.to_dict()
					prop_data['default'] = value

				prop_data['value'] = value
				prop_data['overridable'] = pose_bone.is_property_overridable_library(f'["{prop_name}"]')
				bone_info.custom_props[prop_name] = prop_data

		return bone_info

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

class BoneSetMixin:
	"""Class that provides bone set management to CloudBaseRig."""
	bone_set_defs: Dict[str, str] = OrderedDict()

	def init_bone_set(self, bone_set_name):
		"""Take a bone set definition stored in the class and create a single BoneSet for it."""
		bone_set_defs = type(self).bone_set_defs

		if not bone_set_name in bone_set_defs:
			msg = f"Error: Bone Set definition named {bone_set_name} not found in class {type(self)}. Could not create Bone Set. Report a bug!"
			self.add_log_bug("Bone Set Error", description=msg)
			assert False, msg

		bone_set_def = bone_set_defs[bone_set_name]

		bone_set_def['layers'] = getattr(self.params, bone_set_def['layer_param'])

		new_set = BoneSet(self,
			ui_name = bone_set_def['name'],
			bone_group = getattr(self.params, bone_set_def['param']),
			layers = bone_set_def['layers'],
			preset = bone_set_def['preset'],
			defaults = self.defaults
		)

		self.generator.bone_sets.append(new_set)

		return new_set

	def init_bone_sets(self):
		"""Instantiate all bone sets based on the class's bone_set_defs dictionary."""
		bone_set_defs = type(self).bone_set_defs
		for bone_set_name in bone_set_defs.keys():
			self.bone_sets[bone_set_name] = self.init_bone_set(bone_set_name)

	##############################
	# UI
	@classmethod
	def draw_bone_sets_list(cls, layout, context, params):
		"""Drawing the Bone Sets section of the Rigify Parameters."""
		obj = context.object
		cloudrig = obj.data.cloudrig_parameters
		active_pb = context.active_pose_bone
		rigify_params = active_pb.rigify_parameters
		active_idx = rigify_params.CR_active_bone_set_index

		if len(cloudrig.ui_bone_sets) == 0 or \
				active_idx > len(cloudrig.ui_bone_sets) or \
				cloudrig.ui_bone_sets[active_idx].name not in cls.bone_set_defs:
			split = layout.split(factor=0.1)
			split.row()
			split.label(text="Generate the rig to see Bone Set parameters.")
			return

		active_bone_set = cloudrig.ui_bone_sets[active_idx]

		list_column = draw_ui_list(
			layout
			,context
			,class_name = 'CLOUDRIG_UL_bone_set'
			,list_path = 'object.data.cloudrig_parameters.ui_bone_sets'
			,active_index_path = 'active_pose_bone.rigify_parameters.CR_active_bone_set_index'
			,insertion_operators = False
			,move_operators = False
			,type='GRID' if cloudrig.bone_set_use_grid_layout else 'DEFAULT'
			,columns=3
		)
		eye_icon = 'HIDE_OFF' if rigify_params.CR_show_advanced_bone_sets else 'HIDE_ON'
		list_column.prop(rigify_params, 'CR_show_advanced_bone_sets', text="", emboss=False, icon=eye_icon)
		layout_icon = 'MESH_GRID' if cloudrig.bone_set_use_grid_layout else 'COLLAPSEMENU'
		list_column.prop(cloudrig, 'bone_set_use_grid_layout', text="", emboss=False, icon=layout_icon)

		if not any(filter(lambda x: x>0, CLOUDRIG_UL_bone_set.flt_flags)):
			# If there are no items visible in the list
			layout.label(text="No BoneSet to show. Clear the search filter or re-generate the rig!")
			return
		elif not CLOUDRIG_UL_bone_set.flt_flags[params.CR_active_bone_set_index]:
			# If the active item is not visible
			return

		set_info = cls.bone_set_defs[active_bone_set.name]
		split = layout.row().split(factor=0.8)
		cls.draw_prop_search(split.row(), params, set_info['param'], obj.pose, "bone_groups", text="Bone Group")
		bone_group_name = getattr(params, set_info['param'])
		bone_group = obj.pose.bone_groups.get(bone_group_name)
		if bone_group:
			row = split.row(align=True)

			if bone_group.color_set != 'DEFAULT':
				row.prop(bone_group, 'color_set', text="", icon_only=True)
				row = row.row(align=True)
				row.enabled = bone_group.is_custom_color_set
				row.prop(bone_group.colors, "normal", text="")
				row.prop(bone_group.colors, "select", text="")
				row.prop(bone_group.colors, "active", text="")
			else:
				row.prop(bone_group, 'color_set', text="", icon='DOWNARROW_HLT')

		layout.use_property_split=False
		draw_layers_ui(
			layout = layout, 
			rig = obj, 
			show_unnamed_selected_layers = True,
			show_hidden_checkbox = True, 
			layer_prop_owner = params, 
			layer_prop_name = set_info['layer_param']
		)


	@classmethod
	def is_bone_set_used(cls, params, set_info):
		"""Override in child classes to be able to check for unused bone sets based on current parameters."""
		if set_info['is_advanced']:
			return params.CR_show_advanced_bone_sets
		return True

	##############################
	# Parameters

	@classmethod
	def define_bone_set(cls, params, ui_name, default_group="", default_layers=[0], is_advanced=False, preset=-1):
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

		# TODO: Why are we not just creating a class-level BoneSet instance to store here?
		# Even if that's not a good idea, we could make a UIBoneSet class and instance that.
		cls.bone_set_defs[ui_name] = {
			'name'			: ui_name
			,'preset'		: preset			# Bone Group color preset to use in case the bone group doesn't already exist.
			,'param' 	 	: param_name		# Name of the bone group name parameter
			,'layer_param'	: layer_param_name	# Name of the bone layers parameter
			,'is_advanced'	: is_advanced
		}
		return ui_name

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		# For correct behaviour on Reload Scripts. (Not sure if needed)
		cls.bone_set_defs = OrderedDict()
		params.CR_show_advanced_bone_sets = BoolProperty(name="Advanced Bone Sets", description="Reveal bone sets of helper bones")
		params.CR_active_bone_set_index = IntProperty()

##########################
#### Bone Sets UIList ####
##########################
class UIBoneSet(PropertyGroup):
	"""This class is to bridge the data between Blender's UI and the generator."""
	# The reason we can't use this for the actual Bone Set class used during generation is that
	# the properties of the bone set must be defined during registration, and CollectionProperties
	# are not yet ready at that time. (They only become "real" after registration is complete.)
	bone: StringProperty()
	param_name: StringProperty(description="Name of the Rigify Parameter holding the bone group name")
	layer_param: StringProperty(description="Name of the Rigify Parameter holding the bone layer BoolVectorProperty")

class CLOUDRIG_UL_bone_set(UIList):
	flt_flags = []

	def draw_filter(self, context, layout):
		layout.prop(self, 'filter_name', text="")

	def filter_items(self, context, data, propname):
		flt_flags = []
		flt_neworder = []
		ui_bone_sets = getattr(data, propname)

		helper_funcs = UI_UL_list

		# Always sort alphabetical.
		flt_neworder = helper_funcs.sort_items_by_name(ui_bone_sets, "name")

		if self.filter_name:
			flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, ui_bone_sets, "name")

		if not flt_flags:
			flt_flags = [self.bitflag_filter_item] * len(ui_bone_sets)

		obj = context.object
		cloudrig = obj.data.cloudrig_parameters
		active_pb = context.active_pose_bone
		rig_class = find_rig_class(active_pb.rigify_type)

		for idx, ui_bone_set in enumerate(ui_bone_sets):
			if ui_bone_set.bone != context.active_pose_bone.name:
				# Filter bone set definitions not belonging to this bone
				flt_flags[idx] = 0

			if ui_bone_set.name not in rig_class.bone_set_defs:
				flt_flags[idx] = 0
			else:
				bone_set_def = rig_class.bone_set_defs[ui_bone_set.name]
				if not rig_class.is_bone_set_used(active_pb.rigify_parameters, bone_set_def):
					# Filter bone sets that are not used based on current parameters
					flt_flags[idx] = 0

		type(self).flt_flags = flt_flags
		return flt_flags, flt_neworder

	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		ui_bone_set = item
		rig_data = ui_bone_set.id_data
		rigify_layers = rig_data.rigify_layers
		rig = context.object
		pb = rig.pose.bones.get(ui_bone_set.bone)
		param_layers = getattr(pb.rigify_parameters, ui_bone_set.layer_param)
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.label(text=ui_bone_set.name)
			layer_names = ", ".join([layer.name for i, layer in enumerate(rigify_layers) if param_layers[i]])
			row.label(text=layer_names)
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text=ui_bone_set.name)

# registry = [
# 	UIBoneSet
# 	,CLOUDRIG_UL_bone_set
# ]
