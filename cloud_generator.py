import bpy, os
import traceback
from typing import List

from mathutils import Matrix, Vector
from bpy.props import BoolProperty, StringProperty, EnumProperty, PointerProperty, BoolVectorProperty, FloatProperty, CollectionProperty, IntProperty
from rna_prop_ui import rna_idprop_ui_prop_get

from rigify.generate import Generator, Timer, select_object#, create_selection_sets
from rigify import rig_ui_template
from rigify.utils.naming import ORG_PREFIX, MCH_PREFIX, DEF_PREFIX
from rigify.utils.errors import MetarigError
from rigify.ui import rigify_report_exception
from rigify.utils.bones import new_bone

from .bone import BoneSet, BoneInfo, new_bonei
from .utils import mechanism
from . import widgets as cloud_widgets
from .versioning import cloud_metarig_version

from .actions import CloudRigAction
from .troubleshooting import CloudRigLogEntry, CloudLogManager

from .utils.naming import CloudNameManager

separators = [
	(".", ".", "."),
	("-", "-", "-"),
	("_", "_", "_"),
]

class CloudRigProperties(bpy.types.PropertyGroup):
	version: IntProperty(
		name		 = "CloudRig MetaRig Version"
		,description = "For internal use only"
		,default	 = cloud_metarig_version
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
		name		 = "Custom Script"
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
		,description = "Whether to update the deform test action or not"
		,default	 = True
	)
	test_action: PointerProperty(
		name		 = "Test Action"
		,type		 = bpy.types.Action
		,description = "Action which will be generated with the keyframes neccessary to test the whole rig's deformations"
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

	prefix_separator: EnumProperty(
		name		 = "Prefix Separator"
		,description = "Character that separates prefixes in the bone names"
		,items 		 = separators
		,default	 = "-"
	)
	suffix_separator: EnumProperty(
		name		 = "Suffix Separator"
		,description = "Character that separates suffixes in the bone names"
		,items 		 = separators
		,default	 = "."
	)

	override_options: BoolProperty(
		name = "Override Bone Layers"
		,description = "Instead of allowing rig elements to assign deform/mechanism/org bone layers individually, set it from the generator instead."
		,default=False
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

	override_def_layers: BoolProperty(
		name		="Deform"
		,description="Instead of allowing rig elements to assign deform layers individually, set it from the generator instead"
		,default	=True
	)
	def_layers: BoolVectorProperty(
		size = 32,
		subtype = 'LAYER',
		description = "Select what layers this set of bones should be assigned to",
		default = [l==29 for l in range(32)]
	)

	override_mch_layers: BoolProperty(
		name		="Mechanism"
		,description="Instead of allowing rig elements to assign mechanism layers individually, set it from the generator instead"
		,default	=True
	)
	mch_layers: BoolVectorProperty(
		size = 32,
		subtype = 'LAYER',
		description = "Select what layers this set of bones should be assigned to",
		default = [l==30 for l in range(32)]
	)

	override_org_layers: BoolProperty(
		name		="Original"
		,description="Instead of allowing rig elements to assign original bones' layers individually, set it from the generator instead"
		,default	=True
	)
	org_layers: BoolVectorProperty(
		size = 32,
		subtype = 'LAYER',
		description = "Select what layers this set of bones should be assigned to",
		default = [l==31 for l in range(32)]
	)

	show_layers_preview_hidden: BoolProperty(
		name		 = "Show Hidden Layers"
		,description = "Include layers whose names start with $ and will be hidden on the rig UI"
		,default	 = True
	)

	actions: CollectionProperty(type=CloudRigAction)
	active_action_index: IntProperty(min=0)

	logs: CollectionProperty(type=CloudRigLogEntry)
	log_show_stack_trace: BoolProperty(
		name		 = "Show Stack Trace"
		,description = "Show stack trace of the selected log entry"
		,default	 = False
	)
	active_log_index: IntProperty(min=0)

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

class CloudGenerator(Generator):
	def __init__(self, context, metarig):
		super().__init__(context, metarig)
		self.params = metarig.data	# Generator parameters are stored in rig data.

		self.scale = max(metarig.dimensions)/10

		self.naming = CloudNameManager(
			prefix_separator = self.params.cloudrig_parameters.prefix_separator
			,suffix_separator = self.params.cloudrig_parameters.suffix_separator)
		separators_match = self.naming.prefix_separator == self.naming.suffix_separator
		assert not separators_match, "Prefix and Suffix separators cannot be the same."

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

		# Flag for whether there are any non-CloudRig rig types in the metarig.
		self.rigify_compatible = False
		for b in metarig.pose.bones:
			if b.rigify_type!='' and 'cloud' not in b.rigify_type:
				self.rigify_compatible = True
				print("Rigify compatible generation enabled.")
				break

	def rigify_assign_layers(self):
		""" Rigify compatibility function: Assign ORG/MCH/DEF layers, only to non-CloudRig types. """
		bone_names = []
		for r in self.rig_list:
			if "cloud" in str(type(r)):
				if hasattr(r, "all_bones"):
					for bi in r.all_bones:
						bone_names.append(bi.name)
				elif "cloud_bone" in str(type(r)):	# TODO: cloud_bone should store bones more consistently with cloud_base.
					bone_names.append(r.bone_name)
					if hasattr(r, "def_bone_name"):
						bone_names.append(r.def_bone_name)

		bones = [b for b in self.obj.data.bones if b.name not in bone_names]

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

	def create_rig_object(self):
		scene = self.scene

		# Check if the generated rig already exists, so we can
		# regenerate in the same object.  If not, create a new
		# object to generate the rig in.

		metaname = self.metarig.name
		rig_name = "RIG" + self.naming.prefix_separator + metaname
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
		# obj.data.pose_position = 'POSE'

		self.obj = obj
		return obj

	def create_root_bones(self):
		# Root bone groups
		self.root_set = BoneSet(
			ui_name = 'Root',
			bone_group = getattr(self.params.cloudrig_parameters, 'root_bone_group'),
			layers = getattr(self.params.cloudrig_parameters, 'root_layers')[:],
			preset = 2,
			defaults = self.defaults
		)
		self.bone_sets.append(self.root_set)

		self.root_bone = None
		if self.params.cloudrig_parameters.create_root:
			self.root_bone = new_bonei(self, self.root_set
				,name				= "root"
				,head				= Vector((0, 0, 0))
				,tail				= Vector((0, self.scale*5, 0))
				,bbone_width		= 1/10
				,custom_shape		= self.ensure_widget("Root")
				,custom_shape_scale = 1.5
				,use_custom_shape_bone_size = True
			)

		if self.params.cloudrig_parameters.double_root:
			self.root_parent_set = BoneSet(
				ui_name = 'Root',
				bone_group = getattr(self.params.cloudrig_parameters, 'root_parent_group'),
				layers = getattr(self.params.cloudrig_parameters, 'root_parent_layers')[:],
				preset = 8,
				defaults = self.defaults
			)
			self.bone_sets.append(self.root_parent_set)
			self.root_parent = mechanism.create_parent_bone(self.root_bone, self.root_parent_set)
			self.root_parent.bone_group = 'Root Parent'	# TODO: this shouldn't be needed!

	def load_ui_script(self):
		"""Load cloudrig.py (CloudRig UI script) into a text datablock, enable register checkbox and execute it."""

		# Check if it already exists
		script_name = "cloudrig.py"
		text = bpy.data.texts.get(script_name)
		# If not, create it.
		if not text:
			text = bpy.data.texts.new(name=script_name)

		text.clear()
		text.use_module = True

		filename = script_name
		filedir = os.path.dirname(os.path.realpath(__file__))
		# filedir = os.path.split(filedir)[0]

		readfile = open(os.path.join(filedir, filename), 'r')

		# The script should have a unique identifier that links it to the rigs that were generated in this file - The .blend filename should be sufficient.
		script_id = bpy.path.basename(bpy.data.filepath).split(".")[0]
		if script_id=="":
			# Default in case the file hasn't been saved yet.
			# Falling back to this could result in an older version of the rig trying to use a newer version of the rig UI script or vice versa, so it should be avoided.
			script_id = "cloudrig"

		self.obj.data['cloudrig'] = script_id

		for line in readfile:
			if 'SCRIPT_ID' in line:
				line = line.replace("SCRIPT_ID", script_id)
			text.write(line)
		readfile.close()

		# Run UI script
		exec(text.as_string(), {})

		return text

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
			self.logger.log("(BUG) Failed to create widget"
				,description = "Failed to load widget named '{widget_name}'."
				,icon = 'URL'
				,operator = 'wm.cloudrig_report_bug'
			)
		return wgt

	def find_bone_info(self, name):
		for rig in self.rig_list:
			if hasattr(rig, "bone_sets"):
				for bs in rig.bone_sets:
					exists = bs.find(name)
					if exists:
						return exists

	def create_action_constraints(self):
		bones = self.obj.pose.bones
		action_defs = self.params.cloudrig_parameters.actions

		rig = self.obj
		for act_def in action_defs:
			if not act_def.enabled: continue
			if not act_def.action: continue
			if not act_def.subtarget: continue

			action = act_def.action
			subtarget = act_def.subtarget

			# Getting a list of pose bones on the rig corresponding to the selected action's keyframes
			bones = []
			for fc in action.fcurves:
				# Extracting bone name from fcurve data path
				if("pose.bones" in fc.data_path):
					bone_name = fc.data_path.split('["')[1].split('"]')[0]

					bone = rig.pose.bones.get(bone_name)
					if(bone and bone not in bones):
						bones.append(bone)

			do_symmetry = self.naming.flipped_name(subtarget)!=subtarget and act_def.symmetrical==True

			# Adding action constraints to the bones
			for b in bones:
				con_name = "Action_" + action.name
				constraints = []

				bone_is_left_side = self.naming.side_is_left(b)

				# If bone name is unflippable...
				if bone_is_left_side==None:
					#...but target bone name is flippable, split constraint in two.
					if do_symmetry:
						c_l = b.constraints.new(type='ACTION')
						c_l.name = con_name + ".L"
						c_l.influence = 0.5
						constraints.append(c_l)
						c_r = b.constraints.new(type='ACTION')
						c_r.influence = 0.5
						c_r.name = con_name + ".R"
						constraints.append(c_r)
					else:
						# if target bone name is not flippable, add the constraint normally.
						c = b.constraints.new(type='ACTION')
						c.name = con_name
						constraints.append(c)
				else:
					# Constraint name should indicate side
					c = b.constraints.new(type='ACTION')
					c.name = con_name + (".L" if bone_is_left_side else ".R")
					constraints.append(c)

				# Configure Action constraints
				for c in constraints:
					# If constraint is not the same side as the control, flip it.
					constraint_is_left_side = self.naming.side_is_left(c)
					control_is_left_side = self.naming.side_is_left(subtarget)
					if constraint_is_left_side != control_is_left_side:
						subtarget = self.naming.flipped_name(subtarget)
					c.target_space = act_def.target_space
					c.transform_channel = act_def.transform_channel
					c.target = rig
					c.subtarget = subtarget
					c.action = action
					c.min = act_def.trans_min
					c.max = act_def.trans_max
					c.frame_start = act_def.frame_start
					c.frame_end = act_def.frame_end
					c.mix_mode = 'BEFORE'
					if c.subtarget!=act_def.subtarget:
						# Flip min/max in some cases.
						if(c.transform_channel in ['ROTATION_Z', 'LOCATION_X']):
							max_tmp = c.max
							c.max = c.min
							c.min = max_tmp

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

		self.defaults['rig'] = obj

		# Ensure it's transforms are cleared.
		backup_matrix = obj.matrix_world.copy()
		obj.matrix_world = Matrix()

		# Keep track of created widgets, so we can add them to Rigify-created Widgets collection at the end.
		self.wgt_collection = self.ensure_widget_collection()

		self.create_root_bones()

		# Rename metarig data (TODO: parameter)
		self.metarig.data.name = "Data_" + self.metarig.name

		# Enable all armature layers during generation. This is to make sure if you try to set a bone as active, it won't fail silently.
		obj.data.layers = [True]*32

		# Make sure X-Mirror editing is disabled, always!!
		obj.data.use_mirror_x = False

		# Nuke log entries
		self.logger = CloudLogManager(self.metarig, self.obj)
		self.logger.clear()

		# Get rid of anim data in case the rig already existed

		# obj.animation_data_clear()
		# obj.data.animation_data_clear()

		select_object(context, obj, deselect_all=True)

		#------------------------------------------
		# Create Group widget
		# self._Generator__create_widget_group("WGTS_" + obj.name)

		t.tick("Create main WGTS: ")

		#------------------------------------------
		# Get parented objects to restore later
		childs = {}  # {object: bone}
		for child in obj.children:
			childs[child] = child.parent_bone

		#------------------------------------------
		# Copy bones from metarig to obj
		self._Generator__duplicate_rig()

		t.tick("Duplicate rig: ")

		#------------------------------------------
		# Add the ORG_PREFIX to the original bones.
		bpy.ops.object.mode_set(mode='OBJECT')

		self._Generator__rename_org_bones()

		t.tick("Make list of org bones: ")

		#------------------------------------------
		# Put the rig_name in the armature custom properties
		rna_idprop_ui_prop_get(obj.data, "rig_id", create=True)
		obj.data["rig_id"] = self.rig_id

		# Nuke all drivers on the rig
		if obj.animation_data:
			for d in obj.animation_data.drivers[:]:
				obj.animation_data.drivers.remove(d)

		self.script = None
		if self.rigify_compatible:
			self.script = rig_ui_template.ScriptGenerator(self)

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.instantiate_rig_tree()

		t.tick("Instantiate rigs: ")

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
				self.logger.log("Bone naming failed", trouble_bone=bi.name, description=f"Bone name {bi.name} ended up being {new_name}")
				bi.name = new_name
			self.bone_owners[new_name] = None

		self.invoke_generate_bones()

		t.tick("Generate bones: ")

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

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.ensure_bone_groups()

		for bi in self.bone_infos:
			pose_bone = obj.pose.bones.get(bi.name)
			if not pose_bone:
				self.logger.log("Bone creation failed"
					,owner_bone = bi.owner_rig.base_bone
					,trouble_bone = bi.name
					,description = f"(BUG) BoneInfo {bi.name} wasn't created for some reason."
					,icon = 'URL'
					,operator = 'wm.cloudrig_report_bug'
				)
				continue

			# Scale bone shape based on B-Bone scale
			bi.write_pose_data(pose_bone)
			if not pose_bone.use_custom_shape_bone_size:
				pose_bone.custom_shape_scale *= bi.bbone_width * 10 * self.scale
			pose_bone.bone.bbone_x = bi.bbone_width * self.scale
			pose_bone.bone.bbone_z = bi.bbone_width * self.scale
			pose_bone.bone.envelope_distance = bi.bbone_width * self.scale
			pose_bone.bone.head_radius = bi.bbone_width * self.scale
			pose_bone.bone.tail_radius = bi.bbone_width * self.scale

		self.invoke_configure_bones()

		self.create_action_constraints()

		t.tick("Configure bones: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='EDIT')

		self.invoke_apply_bones()

		# Rigify automatically parents bones that have no parent to the root bone.
		# This is fine, but we want to undo this when the bone has an Armature constraint, since such bones should never have a parent.
		# NOTE: This could be done via self.generator.disable_auto_parent(bone_name).
		for eb in obj.data.edit_bones:
			pb = obj.pose.bones.get(eb.name)
			for c in pb.constraints:
				if c.type=='ARMATURE':
					eb.parent = None
					break

		t.tick("Apply bones: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.invoke_rig_bones()

		# Refresh constraints... without this, some armature constraints think they have an error when they don't.
		for pb in obj.pose.bones:
			for c in pb.constraints:
				c.influence = c.influence

		t.tick("Rig bones: ")

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

		# Execute custom script
		script = self.params.cloudrig_parameters.custom_script
		if script:
			exec(script.as_string(), {})

		# Load and execute cloudrig.py rig UI script
		obj.data['script'] = self.load_ui_script()

		# Armature display settings
		obj.display_type = self.metarig.display_type
		obj.data.display_type = self.metarig.data.display_type

		self.invoke_finalize()

		# TODO: For some reason when cloud_bone adds constraints to a bone, 
		# sometimes those constraints can be invalid even though they aren't actually.
		for pb in obj.pose.bones:
			for c in pb.constraints:
				if hasattr(c, 'subtarget'):
					c.subtarget = c.subtarget

		t.tick("Finalize: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self._Generator__assign_widgets()

		# Create Selection Sets
		create_selection_sets(obj, metarig)

		# Create test animation
		if self.params.cloudrig_parameters.generate_test_action:
			for rig in self.rig_list:
				if hasattr(rig.params, 'CR_fk_chain_test_animation_generate') and rig.params.CR_fk_chain_test_animation_generate:
					action = self.ensure_test_action()
					self.create_test_animation(action)
					break
		
		# Cheap troubleshooting
		self.logger.report_unused_named_layers()
		self.logger.report_invalid_drivers()

		t.tick("The rest: ")

		#----------------------------------
		# Deconfigure
		bpy.ops.object.mode_set(mode='OBJECT')
		obj.data.pose_position = 'POSE'
		# Restore rig object matrix to what it was before generation.
		obj.matrix_world = backup_matrix

		# Restore parent to bones
		for child, sub_parent in childs.items():
			if sub_parent in obj.pose.bones:
				mat = child.matrix_world.copy()
				child.parent_bone = sub_parent
				child.matrix_world = mat

		# Refresh drivers
		bpy.ops.object.cloudrig_refresh_drivers(selected_only=False)

def generate_rig(context, metarig):
	""" Generates a rig from a metarig.	"""
	# Initial configuration
	rest_backup = metarig.data.pose_position
	metarig.data.pose_position = 'REST'

	try:
		CloudGenerator(context, metarig).generate()

		metarig.data.pose_position = rest_backup

	except Exception as e:
		# Cleanup if something goes wrong
		print("Rigify: failed to generate rig.")

		bpy.ops.object.mode_set(mode='OBJECT')
		metarig.data.pose_position = rest_backup

		# Continue the exception
		raise e

class CLOUDRIG_OT_generate(bpy.types.Operator):
	"""Generates a rig from the active metarig armature using the CloudRig generator"""

	bl_idname = "pose.cloudrig_generate"
	bl_label = "CloudRig Generate Rig"
	bl_options = {'UNDO'}
	bl_description = 'Generates a rig from the active metarig armature using the CloudRig generator'

	def execute(self, context):
		try:
			generate_rig(context, context.object)
		except MetarigError as rig_exception:
			traceback.print_exc()

			rigify_report_exception(self, rig_exception)
		except Exception as rig_exception:
			traceback.print_exc()

			self.report({'ERROR'}, 'Generation has thrown an exception: ' + str(rig_exception))
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