
from typing import List

import bpy, os
import traceback
from datetime import datetime

from mathutils import Matrix, Vector
from bpy.props import (BoolProperty, StringProperty, EnumProperty, 
			PointerProperty, BoolVectorProperty, CollectionProperty, IntProperty)
from rna_prop_ui import rna_idprop_ui_prop_get

from rigify.generate import Generator, Timer, select_object
from rigify import rig_ui_template
from rigify.utils.naming import ORG_PREFIX, MCH_PREFIX, DEF_PREFIX
from rigify.utils.errors import MetarigError
from rigify.ui import rigify_report_exception
from rigify.utils.bones import new_bone

from .bone_set import BoneSet, UIBoneSet
from .utils import mechanism
from .utils.ui import redraw_viewport, wipe_ui_data
from . import widgets as cloud_widgets
from .versioning import cloud_metarig_version

from .actions import ActionSlot
from .troubleshooting import CloudRigLogEntry, CloudLogManager

from .utils.naming import CloudNameManager
from .utils.object import EnsureVisible

class CloudRigProperties(bpy.types.PropertyGroup):
	version: IntProperty(
		name		 = "CloudRig MetaRig Version"
		,description = "For internal use only"
		,default	 = -1
	)
	options: BoolProperty(
		name		 = "CloudRig Settings"
		,description = "Show CloudRig Settings"
		,default	 = False
	)
	create_root: BoolProperty(
		name		 = "Create Root"
		,description = "Create the root control"
		,default	 = True
	)
	double_root: BoolProperty(
		name		 = "Double Root"
		,description = "Create two root controls"
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

	mechanism_movable: BoolProperty(
		name		 = "Movable Helpers"
		,description = "Whether helper bones can be moved or not"
		,default	 = True
	)
	mechanism_selectable: BoolProperty(
		name		 = "Selectable Helpers"
		,description = "Whether helper bones can be selected or not"
		,default	 = True
	)

	root_bone_group: StringProperty(
		name="Root"
		,description="Bone Group to assign the root bone to"
		,default="Root"
	)
	root_layers: BoolVectorProperty(
		size = 32,
		subtype = 'LAYER',
		description = "Layers to assign the root bone to",
		default = [l==0 for l in range(32)]
	)

	root_parent_group: StringProperty(
		name="Root Parent"
		,description="Bone Group to assign the second root bone to"
		,default="Root Parent"
	)
	root_parent_layers: BoolVectorProperty(
		size = 32,
		subtype = 'LAYER',
		description = "Layers to assign the the second root bone to",
		default = [l==0 for l in range(32)]
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

def create_selection_sets(obj, metarig):
	# Check if selection sets addon is installed
	if 'bone_selection_groups' not in bpy.context.preferences.addons \
			and 'bone_selection_sets' not in bpy.context.preferences.addons:
		return

	obj.selection_sets.clear()

	for i, name in enumerate(metarig.data.rigify_layers.keys()):
		if name == '' or not metarig.data.rigify_layers[i].selset:
			continue

		selset = obj.selection_sets.add()
		selset.name = name

		for b in obj.pose.bones:
			if b.bone.layers[i] and b.name not in selset.bone_ids:
				bone_id = selset.bone_ids.add()
				bone_id.name = b.name

def load_script(file_path="", file_name="cloudrig.py", search="", replace=""):
	"""Load a text file into a text datablock, enable register checkbox and execute it.
	Also run an optional search and replace on the file content.
	"""

	# Check if it already exists
	text = bpy.data.texts.get(file_name)
	# If not, create it.
	if not text:
		text = bpy.data.texts.new(name=file_name)

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

class ParentingData:
	def __init__(self, obj: bpy.types.Object):
		self.parent = obj.parent
		self.parent_type = obj.parent_type # can be BONE, ARMATURE, OBJECT.
		self.parent_bone = obj.parent_bone # If parent type is BONE, use this as the bone name.
		self.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
		self.matrix_world = obj.matrix_world.copy()

		self.bone_constraint_targets = {}
		for c in obj.constraints:
			if hasattr(c, 'subtarget') and c.subtarget != "":
				self.bone_constraint_targets[c.name] = c.subtarget
				c.subtarget = ""
			if c.type == 'ARMATURE':
				subtargets = []
				for tar in c.targets:
					if tar.target == self.parent:
						subtargets.append(tar.subtarget)
						tar.target = None
				self.bone_constraint_targets[c.name] = subtargets

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
			if b.rigify_type!='' and 'cloud' not in b.rigify_type and 'sprite_fright' not in b.rigify_type:
				self.rigify_compatible = True
				print("Rigify compatible generation enabled.")
				break

	def find_bone_info(self, name):
		for rig in self.rig_list:
			if hasattr(rig, "bone_sets"):
				for bs in rig.bone_sets:
					exists = bs.find(name)
					if exists:
						return exists

	def rigify_assign_layers(self):
		""" Rigify compatibility function: Assign ORG/MCH/DEF layers, only to non-CloudRig types. """
		cloudrig_bones = []
		for rig in self.rig_list:
			if "cloud" in str(type(rig)):
				for bone_set in rig.bone_sets:
					for bone_info in bone_set:
						cloudrig_bones.append(bone_info.name)

		bones = [b for b in self.obj.data.bones if b.name not in cloudrig_bones]

		# Every bone that has a name starting with "DEF-" make deforming.  All the
		# others make non-deforming.
		for bone in bones:
			name = bone.name

			bone.use_deform = name.startswith(DEF_PREFIX)

			# Move all the original bones to their layer.
			if name.startswith(ORG_PREFIX):
				bone.layers = self.params.cloudrig_parameters.org_layers
			# Move all the bones with names starting with "MCH-" to their layer.
			elif name.startswith(MCH_PREFIX):
				bone.layers = self.params.cloudrig_parameters.mch_layers
			# Move all the bones with names starting with "DEF-" to their layer.
			elif name.startswith(DEF_PREFIX):
				bone.layers = self.params.cloudrig_parameters.def_layers

			bone.bbone_x = bone.bbone_z = bone.length * 0.05

	def update_bone_set_ui_info(self):
		"""Keep in sync the bone_sets CollectionProperty stored in the generator parameters,
		with the bone set parameters stored in RigifyParameters. We copy the data from the latter to the former."""

		# Nuke data
		ui_bone_sets = self.metarig.data.cloudrig_parameters.ui_bone_sets
		ui_bone_sets.clear()
		for pb in self.metarig.pose.bones:
			if pb.rigify_type == '':
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
		scene = self.scene

		# Check if the generated rig already exists, so we can
		# regenerate in the same object.  If not, create a new
		# object to generate the rig in.

		metaname = self.metarig.name
		rig_name = "RIG-" + metaname
		if "META" in metaname:
			rig_name = metaname.replace("META", "RIG")

		# Try to find object from the generator parameter.
		obj = self.params.rigify_target_rig
		if not obj:
			# Try to find object in scene.
			obj = scene.objects.get(rig_name)
		if not obj:
			# Try to find object in file.
			obj = bpy.data.objects.get(rig_name)
		if not obj:
			# Object wasn't found anywhere, so create it.
			obj = bpy.data.objects.new(rig_name, bpy.data.armatures.new(rig_name))

		assert obj, "Failed to find or create object!"
		obj.data.name = "Data_" + obj.name

		# Ensure rig is in the metarig's collection.
		if obj.name not in self.collection.objects:
			self.collection.objects.link(obj)

		self.params.rigify_target_rig = obj

		self.obj = obj
		return obj

	# TODO: Perhaps instead of letting the generator handle the root bone directly, 
	# it should be left up to the user, but we can still provide a cloud_root 
	# rig type to handle bone set assignments and widgets 
	# (It would be nearly identical to cloud_copy, and I guess by default it might spawn a deform bone)
	def create_root_bones(self):
		# Root bone groups
		self.root_set = BoneSet(self,
			ui_name = 'Root',
			bone_group = getattr(self.params.cloudrig_parameters, 'root_bone_group'), # TODO why is this using getattr?
			layers = getattr(self.params.cloudrig_parameters, 'root_layers')[:],
			preset = 2,
			defaults = self.defaults
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
			self.root_parent = mechanism.create_parent_bone(self, self.root_bone, self.root_parent_set)
			self.root_parent.bone_group = 'Root Parent'	# TODO: this shouldn't be needed!

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
	def ensure_widget_collection(self):
		""" Find or create the collection where rig widgets should be stored. """ # TODO: Rigify compatibility.
		wgt_collection = self.params.cloudrig_parameters.widget_collection
		if wgt_collection:
			return wgt_collection

		coll_name = "widgets_" + self.obj.name.replace("RIG-", "").lower()

		# Try finding the widgets collection anywhere.
		wgt_collection = bpy.data.collections.get(coll_name)

		if not wgt_collection:
			# Create a Widgets collection within the master collection.
			wgt_collection = bpy.data.collections.new(coll_name)
			bpy.context.scene.collection.children.link(wgt_collection)
			self.params.cloudrig_parameters.widget_collection = wgt_collection
			self.metarig.data.cloudrig_parameters.widget_collection = wgt_collection

		wgt_collection.hide_viewport=True
		wgt_collection.hide_render=True
		return wgt_collection

	def ensure_widget(self, widget_name):
		wgt = cloud_widgets.ensure_widget(
			widget_name
			,overwrite = self.params.rigify_force_widget_update
			,collection = self.wgt_collection
		)
		if not wgt:
			self.logger.log_bug("Failed to create widget"
				,description = f"Failed to load widget named '{widget_name}'."
			)
		return wgt

	def add_to_widget_collection(self, widget_ob):
		if not self.wgt_collection:
			return
		if widget_ob.name not in self.wgt_collection.objects:
			self.wgt_collection.objects.link(widget_ob)
		if widget_ob.name in bpy.context.scene.collection.objects:
			bpy.context.scene.collection.objects.unlink(widget_ob)

	### Action set-up
	def create_action_constraints(self):
		# TODO: This gigantic function should be split up! And possibly moved to a separate class that can be inherited or composited by the generator.
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

	##############################
	### Console spam avoidance ###
	##############################
	# TODO: This solution to avoid console spamming is not viable. 
	# There are just too many ways to create references to bones, and trying to account for all of them is just dumb.
	# Instead, we should generate the rig in a separate, temporary rig, then either join it into the existing object or use
	# Blender's built-in "replace references" function (which afaik is crash prone) to replace the previous rig with the newly generated one.
	# This would also mean that failed generations don't destroy the rig, which is pretty good.

	def save_modifiers(self) -> List[bpy.types.Modifier]:
		"""Save names of modifiers which target our rig, then set that target to None.
		This is because some modifiers spam the console and introduce lag when their target bone is missing,
		and the target bone will be missing until the rig is generated.
		"""
		modifiers = {}
		for o in bpy.data.objects:
			for m in o.modifiers:
				if hasattr(m, 'object') and m.object == self.obj:
					if o.name in modifiers:
						modifiers[o.name].append(m.name)
					else:
						modifiers[o.name] = [m.name]
					m.object = None
		self.modifiers = modifiers
		return modifiers

	def restore_modifiers(self):
		"""Assign the rig as the target object of all saved modifiers."""
		for ob_name in self.modifiers.keys():
			ob = bpy.data.objects.get(ob_name)
			if not ob: continue
			for m_name in self.modifiers[ob_name]:
				m = ob.modifiers.get(m_name)
				if not m: continue
				m.object = self.obj

	def save_parenting_info(self) -> dict:
		rig = self.obj
		assert rig.data.pose_position == 'REST'

		# Get parented objects to restore later
		child_objs = list(rig.children[:])
		for o in bpy.data.objects:
			for c in o.constraints:
				if c.type == 'ARMATURE':
					for tar in c.targets:
						if tar.target == rig and o not in child_objs:
							child_objs.append(o)

		self.children_data = {} # {child_object: ParentingData}
		for child_ob in child_objs:
			self.children_data[child_ob] = ParentingData(child_ob)
			child_ob.parent = None

		return self.children_data

	def restore_parenting_info(self):
		for child, child_data in self.children_data.items():
			child.parent = child_data.parent
			child.parent_type = child_data.parent_type
			child.parent_bone = child_data.parent_bone
			child.matrix_parent_inverse = child_data.matrix_parent_inverse.copy()
			if 'matrix_world' not in child:
				child.matrix_world = child_data.matrix_world.copy()
			else:
				child.matrix_world = Matrix(child['matrix_world'])

			bone_constraint_targets = child_data.bone_constraint_targets
			for c_name in bone_constraint_targets.keys():
				c = child.constraints[c_name]
				if c.type == 'ARMATURE':
					subtargets = bone_constraint_targets[c_name]
					for t in c.targets:
						if t.subtarget in subtargets:
							t.target = self.obj
				else:
					c.subtarget = bone_constraint_targets[c_name]

	### Driver management
	def nuke_drivers(self):
		# Nuke all drivers on the rig
		if self.obj.animation_data:
			datablocks = [self.obj, self.obj.data]
			for db in datablocks:
				if not hasattr(db.animation_data, 'drivers'): continue
				if not db.animation_data: continue

				for d in db.animation_data.drivers[:]:
					db.animation_data.drivers.remove(d)

	def map_drivers(self):
		"""Create a dictionary matching bone names to full data paths of drivers that belong to those bones."""
		# This is for optimization, so we don't have to loop through every driver for every bone when relinking drivers.
		self.driver_map = {}
		if not self.obj.animation_data:
			return
		for fc in self.obj.animation_data.drivers:
			data_path = fc.data_path
			if "pose.bones" in data_path:
				bone_name = data_path.split('pose.bones["')[1].split('"]')[0]
				if bone_name not in self.driver_map:
					self.driver_map[bone_name] = []
				self.driver_map[bone_name].append((data_path, fc.array_index))

	def generate(self):
		print("CloudRig Generation begin")

		context = self.context
		metarig = self.metarig
		t = Timer()

		self.collection = context.scene.collection
		if len(self.metarig.users_collection) > 0:
			self.collection = self.metarig.users_collection[0]

		bpy.ops.object.mode_set(mode='OBJECT')

		#------------------------------------------
		# Create/find the rig object and set it up
		obj = self.create_rig_object()
		obj.data.pose_position = 'REST'
		self.context.view_layer.update()	# This is necessary to make sure child object matrices are updated after switching the rig to rest pose!

		self.nuke_drivers()
		wipe_ui_data(obj)
		self.logger.rig = obj
		self.logger.metarig = metarig

		# Update metarig version
		metarig.data.cloudrig_parameters.version = cloud_metarig_version

		self.defaults['rig'] = obj

		# Ensure it's transforms are cleared.
		self.backup_matrix = obj.matrix_world.copy()
		obj.matrix_world = Matrix()

		# Collection to keep track of bone widgets
		self.wgt_collection = self.ensure_widget_collection()

		self.create_root_bones()

		# Rename metarig data (TODO: parameter)
		self.metarig.data.name = "Data_" + self.metarig.name

		# Enable all armature layers during generation. This is to make sure if you try to set a bone as active, it won't fail silently.
		obj.data.layers = [True]*32

		# Make sure X-Mirror editing is disabled, always!!
		obj.data.use_mirror_x = False

		# Get rid of anim data in case the rig already existed

		# obj.animation_data_clear()
		# obj.data.animation_data_clear()

		select_object(context, obj, deselect_all=True)

		#------------------------------------------
		# Create Group widget
		# self._Generator__create_widget_group("WGTS_" + obj.name)

		t.tick("Create main WGTS: ")

		#------------------------------------------
		# Remove some relationships that will be restored later, to avoid console spam.
		self.save_parenting_info()
		self.save_modifiers()

		#------------------------------------------
		# Copy bones from metarig to obj
		self.nuke_drivers()

		self._Generator__duplicate_rig()

		t.tick("Duplicate rig: ")
		redraw_viewport()

		bpy.ops.object.mode_set(mode='OBJECT')
		self.map_drivers()

		#------------------------------------------
		# Put the rig_name in the armature custom properties
		# if self.rigify_compatible:	# Adding the rig_id is still useful because it's used to not display metarig UI on generated rigs. Not the biggest fan though. Metarigs should be marked rather than non-metarigs!
		rna_idprop_ui_prop_get(obj.data, "rig_id", create=True)
		obj.data["rig_id"] = self.rig_id

		self.script = None
		if self.rigify_compatible:
			self.script = rig_ui_template.ScriptGenerator(self)

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.instantiate_rig_tree()
		# HACK
		# cloud_tweak rigs should be pushed to the end of the list! This is not too hacky, but:
		# cloud_chain_anchor should be pushed to before the first cloud_face_chain.
		# I don't hate this in concept, this just feels like an awkward way to implement it.
		# It would be nicer if the rig class would know how to sort its instances in the rig list.
		# Then the generator could call some Rig.sort(cls, rig_list) function to let each rig sort the rig execution order as it wishes.
		# That way the generator doesn't have to give special treatment to various rig types, which is the hacky part of this.
		from .rigs.cloud_tweak import CloudTweakRig
		from .rigs.cloud_chain_anchor import CloudChainAnchorRig
		from .rigs.cloud_face_chain import CloudFaceChainRig
		first_face = -1
		for i, rig in enumerate(self.rig_list[:]):
			if isinstance(rig, CloudTweakRig) or isinstance(rig, CloudChainAnchorRig):
				self.rig_list.remove(rig)
				self.rig_list.append(rig)
			if isinstance(rig, CloudFaceChainRig) and first_face==-1:
				first_face = i
		for rig in self.rig_list[:]:
			if isinstance(rig, CloudChainAnchorRig):
				self.rig_list.remove(rig)
				self.rig_list.insert(first_face, rig)

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

		for bi in self.bone_infos:
			if bi.name in self.obj.data.edit_bones:
				# print(f"Warning: Bone {bi.name} already exists, skipping. This should never happen!") #TODO: This happens for ORG bones now that we load into BoneInfo objects.
				continue
			new_name = new_bone(self.obj, bi.name)
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
			edit_bone = self.obj.data.edit_bones.get(bi.name)
			bi.write_edit_data(self.obj, edit_bone)

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
			pose_bone.bone.bbone_x = bi.bbone_width * self.scale
			pose_bone.bone.bbone_z = bi.bbone_width * self.scale
			pose_bone.bone.envelope_distance = bi.bbone_width * self.scale
			pose_bone.bone.head_radius = bi.bbone_width * self.scale
			pose_bone.bone.tail_radius = bi.bbone_width * self.scale

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

		# HACK: Refresh constraints... without this, some armature constraints think they have an error when they don't.
		for pb in obj.pose.bones:
			for c in pb.constraints:
				c.influence = c.influence

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

		# Create Selection Sets
		# create_selection_sets(obj, metarig)	# TODO: Add a toggle to preserve selection sets.

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
		obj.data['script'] = load_script(
			file_path = os.path.dirname(os.path.realpath(__file__))
			,file_name="cloudrig.py"
			,search="SCRIPT_ID"
			,replace=script_id
		)

		# Armature display settings
		obj.display_type = self.metarig.display_type
		obj.data.display_type = self.metarig.data.display_type

		self.invoke_finalize()

		# HACK: For some reason when cloud_tweak adds constraints to a bone,
		# sometimes those constraints can be invalid even though they aren't actually.
		for pb in obj.pose.bones:
			for c in pb.constraints:
				if hasattr(c, 'subtarget'):
					c.subtarget = c.subtarget

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

		# Troubleshooting
		today = datetime.today()
		now = datetime.now()
		obj.data['generation_date'] = f"{today.year}-{today.month}-{today.day}"
		obj.data['generation_time'] = f"{now.hour}:{now.minute}:{now.second}"

		# HACK: Stretch constraints seem to get incorrect length. TODO: Is this still necessary, now that we ensure rigs are properly reset early on in generation?
		for pb in obj.pose.bones:
			for c in pb.constraints:
				if c.type=='STRETCH_TO':
					bone_info = self.find_bone_info(pb.name)
					if not bone_info: continue # This should only happen with non-Cloudrig rigs.
					con_info = bone_info.get_constraint(c.name)
					if con_info and 'rest_length' in con_info:
						c.rest_length = con_info.rest_length
					else:
						c.rest_length = pb.length

		# Only leave Force Widget Update enabled until the next generation. TODO: This is bad UX. Would work better as a pop-up parameter, but we don't want to give a popup to something as commonly used as generation. Maybe Widget updating should just be faster! Then this parameter can go away altogether!
		self.metarig.data.rigify_force_widget_update = False

		# Make sure Hidden Layers checkbox is saved in the generated rig, so it remains even if the Rigify addon is disabled.
		self.obj.data.cloudrig_parameters.show_layers_preview_hidden = False

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
					,description=f"Execution of post-generation script in text datablock {script.name} failed, see stack trace below."
					,note=str(e)
				)
				entry.name = "Post-Gen Error"	# Bit of a hack to make this error play nicely with the CloudRig Execution Error.
				entry.pretty_stack = traceback_str
				# Continue the exception, since a post-generation script execution failure
				# should be considered a rig generation failure.
				raise e

		self.cleanup()
		self.update_bone_set_ui_info()
		t.tick("The rest: ")

	def cleanup(self):
		# Deconfigure
		bpy.ops.object.mode_set(mode='OBJECT')
		self.metarig.data.pose_position = 'POSE'
		self.obj.data.pose_position = 'POSE'

		# Restore object parenting
		if hasattr(self, 'children_data'):
			self.restore_parenting_info()

		# Restore modifier targets
		if hasattr(self, 'modifiers'):
			self.restore_modifiers()

		self.logger.report_unused_named_layers()
		self.logger.report_widgets(self.wgt_collection)

		# Restore rig object matrix to what it was before generation.
		if hasattr(self, 'backup_matrix'):
			self.obj.matrix_world = self.backup_matrix

		# Refresh drivers
		self.logger.report_invalid_drivers()


def generate_rig(context, metarig):
	""" Generates a rig from a metarig.	"""
	meta_visible = EnsureVisible(metarig)
	target_rig = metarig.data.rigify_target_rig
	rig_visible = None
	if target_rig:
		rig_visible = EnsureVisible(target_rig)

	generator = CloudGenerator(context, metarig)
	try:
		generator.generate()
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