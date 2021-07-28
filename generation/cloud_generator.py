
from typing import List, Dict, Tuple

import bpy, os, addon_utils, traceback
from bone_selection_sets import from_json, to_json
from datetime import datetime

from mathutils import Matrix, Vector
from bpy.props import (BoolProperty, StringProperty,
			PointerProperty, BoolVectorProperty, CollectionProperty, IntProperty)
from rna_prop_ui import rna_idprop_ui_prop_get

from rigify.generate import Generator, Timer, select_object
from rigify import rig_ui_template
from rigify.utils.naming import DEF_PREFIX
from rigify.utils.errors import MetarigError
from rigify.ui import rigify_report_exception
from rigify.utils.bones import new_bone
from rigify.utils.mechanism import refresh_all_drivers

from ..rig_features.bone_set import BoneSet, UIBoneSet
from ..rig_features import mechanism
from ..rig_features.ui import redraw_viewport
from ..rig_features.widgets import widgets as cloud_widgets
from ..versioning import cloud_metarig_version

from .actions import ActionSlot
from .troubleshooting import CloudRigLogEntry, CloudLogManager

from .naming import CloudNameManager
from ..rig_features.object import EnsureVisible

class CloudRigProperties(bpy.types.PropertyGroup):
	version: IntProperty(
		name		 = "CloudRig MetaRig Version"
		,description = "For internal use only"
		,default	 = -1
	)
	beginner_mode: BoolProperty(
		name		 = "Beginner Mode"
		,description = "Hide some advanced generator and rig type parameters. Recommended for new users"
		,default	 = True
	)

	create_root: BoolProperty(
		name		 = "Create Root"
		,description = "Create a default root control"
		,default	 = True
	)
	double_root: BoolProperty(
		name		 = "Double Root"
		,description = "Create two default root controls"
		,default	 = False
	)

	custom_script: PointerProperty(
		name		 = "Post-Generation Script"
		,type		 = bpy.types.Text
		,description = "Execute a python script after the rig is generated"
	)
	widget_collection: PointerProperty(
		name		 = "Widgets Collection"
		,type		 = bpy.types.Collection
		,description = "Collection in which widgets will be placed"
	)

	generate_test_action: BoolProperty(
		name		 = "Generate Test Action"
		,description = "Whether to create/update the deform test action or not"
		,default	 = True
	)
	test_action: PointerProperty(
		name		 = "Test Action"
		,type		 = bpy.types.Action
		,description = "Action which will be generated with the keyframes neccessary to test the rig's deformations"
	)

	show_layers_preview_hidden: BoolProperty(
		name		 = "Show Hidden Layers"
		,description = "Show layers whose names start with $ and will be hidden on the rig UI"
		,default	 = True
	)

	action_slots: CollectionProperty(type=ActionSlot)
	active_action_slot_index: IntProperty(min=0)

	logs: CollectionProperty(type=CloudRigLogEntry)
	log_show_stack_trace: BoolProperty(
		name		 = "Show Stack Trace"
		,description = "Show stack trace of the selected log entry"
		,default	 = False
	)
	active_log_index: IntProperty(min=0)

	ui_bone_sets: CollectionProperty(type=UIBoneSet)
	bone_set_use_grid_layout: BoolProperty(name="Use Grid Layout", default=True, description="Switch the list display between a compact grid and a detailed list")

def is_cloud_rig_type(rig_type_name: str):
	return  rig_type_name != "" and \
			('cloud' in rig_type_name or \
			'sprite_fright' in rig_type_name)

def load_script(file_path="", file_name="cloudrig.py", search="", replace="", datablock=None):
	"""Load a text file into a text datablock, enable register checkbox and execute it.
	Also run an optional search and replace on the file content.
	"""

	if datablock:
		text = datablock
	else:
		# Check if it already exists
		text = bpy.data.texts.get(file_name)
		# If not, create it.
		if not text:
			text = bpy.data.texts.new(name=file_name)
			text.use_fake_user = False

	text.clear()
	text.use_module = True

	if file_path=="":
		file_path = os.path.dirname(os.path.realpath(__file__))

	readfile = open(os.path.join(file_path, file_name), 'r')

	for line in readfile:
		if search!="" and replace!="" and search in line:
			line = line.replace(search, replace)
		text.write(line)
	readfile.close()

	# Run UI script
	exec(text.as_string(), {})

	return text

class CloudGenerator(Generator):
	def __init__(self, context, metarig):
		super().__init__(context, metarig)
		self.params = metarig.data	# Generator parameters are stored in rig data.

		metarig.data.pose_position = 'REST'
		context.view_layer.update() # Needed to make sure we get the correct scale
		self.scale = max(metarig.dimensions)/10

		self.naming = CloudNameManager()

		# List that stores a reference to all BoneInfo instances of all rigs.
		# IMPORTANT: This should not be a BoneInfo, just a regular list. Otherwise the LinkedList behaviour gets all messed up!
		# Each BoneInfo should only exist in a single BoneSet!
		self.bone_infos = []
		# List that stores a reference to all BoneSets of all rigs.
		self.bone_sets: List[BoneSet] = []
		# Default kwargs that are passed in to every created BoneInfo
		self.defaults = {
			'rotation_mode' : 'XYZ'
		}

		# Nuke log entries
		self.logger = CloudLogManager(metarig)
		self.logger.clear()

		# Flag for whether there are any non-CloudRig rig types in the metarig.
		self.rigify_compatible = False
		for b in metarig.pose.bones:
			if b.rigify_type != '' and not is_cloud_rig_type(b.rigify_type):
				self.rigify_compatible = True
				print("Rigify compatible generation enabled.")
				break
		
		# Check if Selection Sets addon is enabled
		self.do_sel_sets = addon_utils.check('bone_selection_sets')[1]

	@staticmethod
	def cloudrig_reorder_rigs(rig_list):
		"""Some rig types need special treatment in regards to where they are in 
		the rig generation order."""
		from ..rigs.cloud_tweak import CloudTweakRig
		from ..rigs.cloud_chain_anchor import CloudChainAnchorRig
		from ..rigs.cloud_face_chain import CloudFaceChainRig

		first_face = -1
		for i, rig in enumerate(rig_list[:]):
			if isinstance(rig, CloudTweakRig) or isinstance(rig, CloudChainAnchorRig):
				# cloud_tweak rigs should be generated last.
				rig_list.remove(rig)
				rig_list.append(rig)
			if isinstance(rig, CloudFaceChainRig) and first_face==-1:
				first_face = i
		for rig in rig_list[:]:
			if isinstance(rig, CloudChainAnchorRig):
				# cloud_chain_anchor pushed before the first cloud_face_chain.
				rig_list.remove(rig)
				rig_list.insert(first_face, rig)

	def find_bone_info(self, name):
		for rig in self.rig_list:
			if hasattr(rig, "bone_sets"):
				for bs in list(rig.bone_sets.values()):
					exists = bs.find(name)
					if exists:
						return exists

	def rigify_assign_layers(self):
		""" Rigify compatibility function: Assign ORG/MCH/DEF layers, only to non-CloudRig types. """
		cloudrig_bones = []
		for rig in self.rig_list:
			if "cloud" in str(type(rig)):
				for bone_set in list(rig.bone_sets.values()):
					for bone_info in bone_set:
						cloudrig_bones.append(bone_info.name)

		bones = [b for b in self.obj.data.bones if b.name not in cloudrig_bones]

		# Every bone that has a name starting with "DEF-" make deforming.  All the
		# others make non-deforming.
		for bone in bones:
			name = bone.name
			bone.use_deform = name.startswith(DEF_PREFIX)
			bone.bbone_x = bone.bbone_z = bone.length * 0.05

	def update_bone_set_ui_info(self):
		"""Keep in sync the bone_sets CollectionProperty stored in the generator 
		parameters, with the bone set parameters stored in RigifyParameters. 
		We copy the data from the latter to the former."""

		# Nuke data
		ui_bone_sets = self.metarig.data.cloudrig_parameters.ui_bone_sets
		ui_bone_sets.clear()
		for pb in self.metarig.pose.bones:
			if not is_cloud_rig_type(pb.rigify_type):
				continue
			pb.rigify_parameters.CR_active_bone_set_index = 0
			rig_class = self.find_rig_class(pb.rigify_type)
			rig_bone_set_defs = rig_class.bone_set_defs
			for rig_bone_set_name in rig_bone_set_defs.keys():
				rig_bone_set_def = rig_bone_set_defs[rig_bone_set_name]
				new_ui_set = ui_bone_sets.add()
				new_ui_set.name = rig_bone_set_def['name']
				new_ui_set.bone = pb.name
				new_ui_set.param_name = rig_bone_set_def['param']
				new_ui_set.layer_param = rig_bone_set_def['layer_param']

	def create_rig_object(self):
		"""Create the rig object that will replace the previous generation result."""

		metaname = self.metarig.name
		rig_name = "GENERATING-" + metaname.replace("META", "RIG")
		obj = bpy.data.objects.new(rig_name, bpy.data.armatures.new(rig_name))
		obj.data.name = "Data_" + metaname.replace("META", "RIG")

		# Ensure rig is in the metarig's collection.
		if obj.name not in self.collection.objects:
			self.collection.objects.link(obj)

		# Adding the rig_id necessary to not display metarig UI on generated rigs. 
		# XXX UPSTREAM: Metarigs should be marked rather than non-metarigs!
		rna_idprop_ui_prop_get(obj.data, "rig_id", create=True)
		obj.data["rig_id"] = self.rig_id

		# Timestamp
		today = datetime.today()
		now = datetime.now()
		obj.data['generation_date'] = f"{today.year}-{today.month}-{today.day}"
		obj.data['generation_time'] = f"{now.hour}:{now.minute}:{now.second}"

		# Make sure Hidden Layers checkbox is saved in the generated rig, so it 
		# remains even if the Rigify addon is disabled.
		obj.data.cloudrig_parameters.show_layers_preview_hidden = False

		return obj

	def create_root_bones(self):
		# Root bone groups
		self.root_set = BoneSet(self
			,ui_name = 'Root'
			,bone_group = self.params.cloudrig_parameters.root_bone_group
			,layers = self.params.cloudrig_parameters.root_layers[:]
			,preset = 2
			,defaults = self.defaults
		)
		self.bone_sets.append(self.root_set)

		self.root_bone = None
		if self.params.cloudrig_parameters.create_root:
			self.root_bone = self.root_set.new(
				name				= "root"
				,head				= Vector((0, 0, 0))
				,tail				= Vector((0, self.scale*5, 0))
				,bbone_width		= 1/10
				,custom_shape		= self.ensure_widget("Root")
				,custom_shape_scale = 1.5
				,use_custom_shape_bone_size = True
			)

		if self.params.cloudrig_parameters.double_root:
			self.root_parent_set = BoneSet(self,
				ui_name = 'Root',
				bone_group = getattr(self.params.cloudrig_parameters, 'root_parent_group'),
				layers = getattr(self.params.cloudrig_parameters, 'root_parent_layers')[:],
				preset = 8,
				defaults = self.defaults
			)
			self.bone_sets.append(self.root_parent_set)
			self.root_parent = mechanism.create_parent_bone(self.root_bone, self.root_parent_set)

		# If the Metarig has any Action Slots, create an Action Property Helper bone.
		if len(self.metarig.data.cloudrig_parameters.action_slots) > 0:
			self.action_helper = self.create_action_helper()

	def ensure_bone_groups(self):
		# Wipe any existing bone groups from the target rig.
		if self.obj.pose:
			for bone_group in self.obj.pose.bone_groups:
				self.obj.pose.bone_groups.remove(bone_group)

		for bone_set in self.bone_sets:
			meta_bg = bone_set.ensure_bone_group(self.metarig, overwrite=False)
			if meta_bg:
				bone_set.normal = meta_bg.colors.normal[:]
				bone_set.select = meta_bg.colors.select[:]
				bone_set.active = meta_bg.colors.active[:]
			if self.params.rigify_colors_lock:
				bone_set.select = self.params.rigify_selection_colors.select
				bone_set.active = self.params.rigify_selection_colors.active

			bone_set.ensure_bone_group(self.obj, overwrite=True)

	### Widget management
	def ensure_widget_collection(self, context):
		"""Find or create the collection where rig widgets should be stored."""
		widget_collection = self.params.cloudrig_parameters.widget_collection
		if widget_collection:
			return widget_collection

		coll_name = "widgets_" + self.obj.name.replace("RIG-", "").lower()

		# Try finding the widgets collection anywhere.
		widget_collection = bpy.data.collections.get(coll_name)

		if not widget_collection:
			# Create a Widgets collection within the master collection.
			widget_collection = bpy.data.collections.new(coll_name)
			context.scene.collection.children.link(widget_collection)
			self.params.cloudrig_parameters.widget_collection = widget_collection
			self.metarig.data.cloudrig_parameters.widget_collection = widget_collection

		widget_collection.hide_viewport = True
		widget_collection.hide_render = True
		return widget_collection

	def ensure_widget(self, widget_name):
		wgt = cloud_widgets.ensure_widget(
			widget_name
			,overwrite = self.params.rigify_force_widget_update
			,collection = self.widget_collection
		)
		if not wgt:
			self.logger.log_bug("Failed to create widget"
				,description = f"Failed to load widget named '{widget_name}'."
			)
		return wgt

	def add_to_widget_collection(self, widget_ob):
		context = self.context
		if not self.widget_collection:
			return
		if widget_ob.name not in self.widget_collection.objects:
			self.widget_collection.objects.link(widget_ob)
		if widget_ob.name in context.scene.collection.objects:
			context.scene.collection.objects.unlink(widget_ob)

	### Action set-up
	def create_action_constraints(self):
		rig = self.obj
		action_slots = self.metarig.data.cloudrig_parameters.action_slots

		# Iterate over all Action Slots.
		# Reversed because each constraint gets moved to the top of the stack when created.
		for act_slot in reversed(action_slots):
			if not act_slot.enabled: continue
			action = act_slot.action
			subtarget = act_slot.subtarget

			# Sanity checks and early exit
			if not action:
				self.logger.log("Action missing for an Action Slot.")
				continue
			if subtarget not in rig.pose.bones and not act_slot.is_corrective:
				self.logger.log("Invalid Control Bone for Action"
					,trouble_bone = subtarget
					,description = f"Control Bone {subtarget} doesn't exist in the generated rig for Action Slot {action.name}"
				)
				continue

			act_slot.create_action_constraints(self.action_helper.name)

	def create_action_helper(self):
		action_helper = self.root_set.new(
			name				= "action_props"
			,head				= Vector((0, 0, 0))
			,tail				= Vector((0, self.scale*1, 0))
			,bbone_width		= 1/20
		)
		action_helper.layers = [i==31 for i in range(32)]
		return action_helper

	### Deform test animation generation
	def ensure_test_action(self):
		# Ensure test action exists
		test_action = self.params.cloudrig_parameters.test_action
		if not test_action:
			test_action = bpy.data.actions.new("RIG.DeformTest."+self.obj.name)
			self.metarig.data.cloudrig_parameters.test_action = test_action

		# Nuke all curves
		for fc in test_action.fcurves[:]:
			test_action.fcurves.remove(fc)

		if not self.obj.animation_data:
			self.obj.animation_data_create()

		if not self.obj.animation_data.action:
			self.obj.animation_data.action = test_action

		return test_action

	def create_test_animation(self, action):
		"""Generate deformation test animation.

		In order to generate the test animation, we need to call add_test_animation() on rigs
		in a different order than regular rig execution, and we also want to account for symmetry.

		Usual rig execution is in order of hierarchical levels: highest level gets executed first,
		then all second level rigs, then all third level rigs.
		For the animation, we need a hierarchy to be executed all the way down before moving on to
		the next one.

		Symmetrical rigs should animate at the same time, and with the Y and Z axis rotations flipped.
		"""

		rigs_anim_order = []
		def get_rig_children(rig):
			children = []
			for r in self.rig_list:
				if r.rigify_parent == rig:
					children.append(r)
			return children

		def add_rig_hierarchy_to_animation_order(rig):
			if hasattr(type(rig), 'has_test_animation') and type(rig).has_test_animation:
				rigs_anim_order.append(rig)
			for child_rig in get_rig_children(rig):
				add_rig_hierarchy_to_animation_order(child_rig)

		for root_rig in self.root_rigs:
			add_rig_hierarchy_to_animation_order(root_rig)

		start_frame = 1
		for rig in rigs_anim_order:
			symm_rig = rig.find_symmetry_rig()
			symm_new_start_frame = 1
			new_start_frame = rig.add_test_animation(action, start_frame)
			if symm_rig:
				symm_new_start_frame = symm_rig.add_test_animation(action, start_frame, flip_xyz=[False, True, True])
				rigs_anim_order.remove(symm_rig)
			start_frame = max(new_start_frame, symm_new_start_frame)

	def map_drivers(self) -> Dict[str, Tuple[str, int]]:
		"""Create a dictionary matching bone names to full data paths of drivers that belong to those bones."""
		# This is for optimization, so we don't have to loop through every driver for every bone when relinking drivers.
		driver_map = {}
		if not self.obj.animation_data:
			return
		for fc in self.obj.animation_data.drivers:
			data_path = fc.data_path
			if "pose.bones" in data_path:
				bone_name = data_path.split('pose.bones["')[1].split('"]')[0]
				if bone_name not in driver_map:
					driver_map[bone_name] = []
				driver_map[bone_name].append((data_path, fc.array_index))
		return driver_map

	def preserve_rig_data(self, old_rig, new_rig):
		"""Preserve useful user-inputted information from the previous rig,
		then delete it and re-map all pointers to it to the new rig."""

		# Save selection sets
		if self.do_sel_sets:
			self.context.view_layer.objects.active = old_rig
			for selset in old_rig.selection_sets:
				selset.is_selected = True
			selsets = to_json(self.context)

		# Remove old rig from all of its collections.
		for coll in old_rig.users_collection:
			coll.objects.unlink(old_rig)

		# Swap all references pointing at the old rig to the new rig
		old_rig.id_data.user_remap(new_rig)
		old_name = old_rig.name

		# Preserve transform matrix of previous rig.
		new_rig.matrix_world = old_rig.matrix_world.copy()

		# Preserve assigned action of previous rig.
		if old_rig.animation_data and old_rig.animation_data.action:
			new_rig.animation_data.action = old_rig.animation_data.action

		# Delete the old rig
		bpy.data.objects.remove(old_rig)

		# Preserve object name of previous rig.
		new_rig.name = old_name

		# Select and make active the new rig
		new_rig.select_set(True)
		self.context.view_layer.objects.active = new_rig

		# Preserve selection sets of previous rig.
		if self.do_sel_sets:
			from_json(self.context, selsets)

	def generate(self, context):
		print("CloudRig Generation begin")

		metarig = self.metarig
		t = Timer()

		self.collection = context.scene.collection
		if len(self.metarig.users_collection) > 0:
			self.collection = self.metarig.users_collection[0]

		bpy.ops.object.mode_set(mode='OBJECT')

		#------------------------------------------
		# Create/find the rig object and set it up
		old_rig = self.params.rigify_target_rig
		self.obj = obj = self.create_rig_object()
		obj.data.pose_position = 'REST'
		context.view_layer.update()	# This is necessary to make sure child object matrices are updated after switching the rig to rest pose!

		self.logger.rig = obj
		self.logger.metarig = metarig

		# Update metarig version
		metarig.data.cloudrig_parameters.version = cloud_metarig_version

		self.defaults['rig'] = obj

		# Collection to keep track of bone widgets
		self.widget_collection = self.ensure_widget_collection(context)

		# Rename metarig data
		self.metarig.data.name = "Data_" + self.metarig.name

		select_object(context, obj, deselect_all=True)

		#------------------------------------------
		# Create Group widget
		# self._Generator__create_widget_group("WGTS_" + obj.name)

		t.tick("Create main WGTS: ")

		#------------------------------------------
		# Join a clone of the metarig into the generated rig.
		self._Generator__duplicate_rig()

		# t.tick("Duplicate rig: ")
		redraw_viewport()

		bpy.ops.object.mode_set(mode='OBJECT')
		self.driver_map = self.map_drivers()

		self.script = None
		if self.rigify_compatible:
			self.script = rig_ui_template.ScriptGenerator(self)

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.create_root_bones()
		self.instantiate_rig_tree()
		self.cloudrig_reorder_rigs(self.rig_list)

		t.tick("Instantiate rigs: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.invoke_initialize()

		t.tick("Initialize rigs: ")

		# Copy Rigify Layers from metarig to target rig
		for i in range(len(obj.data.rigify_layers), len(self.metarig.data.rigify_layers)):
			obj.data.rigify_layers.add()
		for i, rig_layer in enumerate(self.metarig.data.rigify_layers):
			target = obj.data.rigify_layers[i]
			source = self.metarig.data.rigify_layers[i]
			target.name = source.name
			target.row = source.row
			target.selset = source.selset
			target.group = source.group

		#------------------------------------------
		bpy.ops.object.mode_set(mode='EDIT')

		self.invoke_prepare_bones()

		t.tick("Prepare bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')
		bpy.ops.object.mode_set(mode='EDIT')

		self.root_bone = None
		if self.params.cloudrig_parameters.create_root:
			self._Generator__create_root_bone()

		# Create real bones from all BoneInfos. No bone data is written here beside the name.
		for bi in self.bone_infos:
			if bi.name in obj.data.edit_bones:
				# This happens for ORG bones that we load into BoneInfo objects,
				# since they already get created by __duplicate_rig()
				continue
			new_name = new_bone(obj, bi.name)
			if new_name != bi.name:
				self.logger.log(
					"Bone naming failed"
					,trouble_bone = bi.name
					,description = f"Bone name {bi.name} ended up being {new_name}. This is a bug unless your bone names were close to 63 characters long to begin with."
				)
				bi.name = new_name
			self.bone_owners[new_name] = None

		self.invoke_generate_bones()

		t.tick("Generate bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')
		bpy.ops.object.mode_set(mode='EDIT')

		self.invoke_parent_bones()

		for bi in self.bone_infos:
			edit_bone = obj.data.edit_bones.get(bi.name)
			bi.write_edit_data(self, edit_bone, context)

		if self.root_bone:
			self._Generator__parent_bones_to_root()

		t.tick("Parent bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.ensure_bone_groups()

		for bi in self.bone_infos:
			pose_bone = obj.pose.bones.get(bi.name)
			if not pose_bone:
				self.logger.log("Bone creation failed"
					,owner_bone = bi.owner_rig.base_bone
					,trouble_bone = bi.name
					,description = f"BoneInfo {bi.name} wasn't created for some reason."
				)
				continue
			
			# Scale bone shape based on B-Bone scale
			bi.write_pose_data(pose_bone)
			if not pose_bone.use_custom_shape_bone_size:
				pose_bone.custom_shape_scale_xyz *= bi.bbone_width * 10 * self.scale

		self.invoke_configure_bones()

		self.create_action_constraints()

		t.tick("Configure bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='EDIT')

		self.invoke_apply_bones()

		# Rigify automatically parents bones that have no parent to the root bone.
		# This is fine, but we want to undo this when the bone has an Armature constraint, since such bones should never have a parent.
		# NOTE: This could be done via self.generator.disable_auto_parent(bone_name).
		# This could also be done as a part of BoneInfo.constraint_add(), with an optional parameter for clarity.
		# Or simply do it manually every time an armature constraint is added, but that really does feel error prone.
		# But the error could be notified in the Rigify Log.
		for eb in obj.data.edit_bones:
			pb = obj.pose.bones.get(eb.name)
			for c in pb.constraints:
				if c.type=='ARMATURE':
					eb.parent = None
					break

		t.tick("Apply bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.invoke_rig_bones()

		t.tick("Rig bones: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		if self.rigify_compatible:
			self.invoke_generate_widgets()
			t.tick("Generate widgets: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		obj.data.layers = self.metarig.data.layers[:]
		obj.data.layers_protected = self.metarig.data.layers_protected[:]
		self._Generator__restore_driver_vars()

		if self.rigify_compatible:
			self.rigify_assign_layers()
			t.tick("Assign layers: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		### Load and execute cloudrig.py rig UI script
		# The script should have a unique identifier that links it to the rigs that were generated in this file - The .blend filename should be sufficient.
		script_id = bpy.path.basename(bpy.data.filepath).split(".")[0]
		# Since this script_id will be used in bl_idnames, let's sanitize it so Blender doesn't complain about invalid bl_idnames.
		# Only keep alphabetical characters and convert them to lowercase.
		script_id = ''.join(e for e in script_id if e.isalpha()).lower()

		if script_id=="":
			# Default in case the file hasn't been saved yet.
			# Falling back to this could result in an older version of the rig trying to use a newer version of the rig UI script or vice versa, so it should be avoided.
			script_id = "cloudrig"

		obj.data['cloudrig'] = script_id
		metarig.data.rigify_rig_ui = obj.data['script'] = load_script(
			file_path = os.path.dirname(os.path.realpath(__file__))
			,file_name = "cloudrig.py"
			,search = "SCRIPT_ID"
			,replace = script_id
			,datablock = metarig.data.rigify_rig_ui
		)

		# Armature display settings
		obj.display_type = self.metarig.display_type
		obj.data.display_type = self.metarig.data.display_type

		self.invoke_finalize()

		t.tick("Finalize: ")
		redraw_viewport()

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self._Generator__assign_widgets()

		# Create test animation
		if self.params.cloudrig_parameters.generate_test_action:
			for rig in self.rig_list:
				if hasattr(rig.params, 'CR_fk_chain_test_animation_generate') and rig.params.CR_fk_chain_test_animation_generate:
					action = self.ensure_test_action()
					self.create_test_animation(action)
					break

		# Only leave Force Widget Update enabled until the next generation.
		# XXX: This is bad UX. Would work better as a pop-up parameter, but we 
		# don't want to give a popup to something as commonly used as generation. 
		# Maybe Widget updating should just be faster! Then this parameter can go away altogether!
		self.metarig.data.rigify_force_widget_update = False

		if old_rig:
			self.preserve_rig_data(old_rig, obj)
		else:
			obj.name = obj.name.replace("GENERATING-", "")

		self.params.rigify_target_rig = obj

		# Execute custom script
		script = self.params.cloudrig_parameters.custom_script
		if script:
			try:
				exec(script.as_string(), {})
			except Exception as e:
				# We can't know type of exception here since code was written by user.
				traceback_str = traceback.format_exc()
				entry = self.logger.log(
					"Post-Generation Script failed."
					,description = f"Execution of post-generation script in text datablock {script.name} failed, see stack trace below."
					,note = str(e)
				)
				entry.name = "Post-Gen Error"	# Specific name to make this error play nicely with the CloudRig Execution Error.
				entry.pretty_stack = traceback_str
				# Continue the exception, since a post-generation script execution failure
				# should be considered a rig generation failure.
				raise e

		self.cleanup()
		self.update_bone_set_ui_info()
		t.tick("The rest: ")

	def cleanup(self):
		"""Clean up after generation has either failed or succeeded."""
		# NOTE: Errors raised in this function won't be handled nicely!
		# It will not be added to the Rigify Log, and relationships won't be 
		# fully restored to their original states.
		
		# Deconfigure
		bpy.ops.object.mode_set(mode='OBJECT')
		self.metarig.data.pose_position = 'POSE'
		self.obj.data.pose_position = 'POSE'

		self.logger.report_unused_named_layers()
		self.logger.report_widgets(self.widget_collection)

		# Refresh drivers
		refresh_all_drivers()
		self.context.view_layer.update()
		self.logger.report_invalid_drivers_on_object_hierarchy(self.obj)


def generate_rig(context, metarig):
	""" Generates a rig from a metarig.	"""
	meta_visible = EnsureVisible(metarig)
	target_rig = metarig.data.rigify_target_rig
	rig_visible = None
	if target_rig:
		rig_visible = EnsureVisible(target_rig)

	generator = CloudGenerator(context, metarig)
	try:
		generator.generate(context)
	except Exception as e:
		# Cleanup if something goes wrong
		generator.cleanup()

		logs = metarig.data.cloudrig_parameters.logs
		if 'Post-Gen Error' in logs:
			# In this case the post-generation error is already in the log,
			# we don't want to clear that and present the user with a bug report button.
			raise e
		# Remove all log entries.
		logs.clear()
		# Add a log entry about the error.
		traceback_str = traceback.format_exc()
		log = generator.logger.log_bug("Execution Error!", op_kwargs={'stack_trace' : traceback_str})
		log.pretty_stack = traceback_str

		# Continue the exception
		raise e

	meta_visible.restore()
	if rig_visible:
		rig_visible.restore()

class CLOUDRIG_OT_generate(bpy.types.Operator):
	"""Generates a rig from the active metarig armature using the CloudRig generator"""

	bl_idname = "pose.cloudrig_generate"
	bl_label = "CloudRig Generate Rig"
	bl_options = {'UNDO'}
	bl_description = 'Generates a rig from the active metarig armature using the CloudRig generator'

	def execute(self, context):
		metarig = context.object
		try:
			generate_rig(context, metarig)
		except MetarigError as rig_exception:
			traceback.print_exc()
			rigify_report_exception(self, rig_exception)
		except Exception as rig_exception:
			traceback.print_exc()
			self.report({'ERROR'}, 'Failed to generate from metarig: ' + metarig.name)
		finally:
			bpy.ops.object.mode_set(mode='OBJECT')

		return {'FINISHED'}

classes = [
	CloudRigProperties,

	CLOUDRIG_OT_generate,
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)
	bpy.types.Armature.cloudrig_parameters = PointerProperty(type=CloudRigProperties)

def unregister():
	from bpy.utils import unregister_class
	for c in classes:
		unregister_class(c)
	del bpy.types.Armature.cloudrig_parameters