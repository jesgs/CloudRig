import bpy, os
from mathutils import Matrix, Vector
from bpy.props import BoolProperty, StringProperty, EnumProperty, PointerProperty, BoolVectorProperty, FloatProperty, CollectionProperty, IntProperty
from rigify.generate import *
from .definitions.bone import BoneSet
from .rigs import cloud_utils
from . import widgets as cloud_widgets
from .actions import CloudRigAction
from .utils import flip_name, name_side_is_left

separators = [
	(".", ".", "."),
	("-", "-", "-"),
	("_", "_", "_"),
]

class CloudRigProperties(bpy.types.PropertyGroup):
	version: FloatProperty(
		name		 = "CloudRig Version"
		,description = "For internal use only"
		,default	 = 0.0
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

	show_actions: BoolProperty(name="Actions")
	actions: CollectionProperty(type=CloudRigAction)
	active_action_index: IntProperty(min=0)

class CloudGenerator(Generator):
	def __init__(self, context, metarig):
		super().__init__(context, metarig)
		self.params = metarig.data	# Generator parameters are stored in rig data.

		self.scale = max(metarig.dimensions)/10

		self.prefix_separator = self.params.cloudrig_parameters.prefix_separator
		self.suffix_separator = self.params.cloudrig_parameters.suffix_separator
		assert self.prefix_separator != self.suffix_separator, "CloudGenerator Error: Prefix and Suffix separators cannot be the same."

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
		rig_name = "RIG" + self.prefix_separator + metaname
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

		assert obj, "Error: Failed to find or create object!"
		obj.data.name = "Data_" + obj.name

		# Ensure rig is in the metarig's collection.
		if obj.name not in self.collection.objects:
			self.collection.objects.link(obj)

		self.params.rigify_target_rig = obj
		# obj.data.pose_position = 'POSE'

		self.obj = obj
		return obj

	def define_root_bone(self):
		# Root bone groups
		self.root_set = BoneSet(
			self,
			ui_name = 'Root',
			bone_group = getattr(self.params.cloudrig_parameters, 'root_bone_group'),
			layers = getattr(self.params.cloudrig_parameters, 'root_layers')[:],
			preset = 2,
			defaults = self.defaults
		)

		self.root_bone = None
		if self.params.cloudrig_parameters.create_root:
			self.root_bone = self.root_set.new(
				name				= "root"
				,head				= Vector((0, 0, 0))
				,tail				= Vector((0, self.scale*5, 0))
				,bbone_width		= 1/3
				,custom_shape		= self.load_widget("Root")
				,custom_shape_scale = 1.5
			)

		if self.params.cloudrig_parameters.double_root:
			self.root_parent_set = BoneSet(
				self,
				ui_name = 'Root',
				bone_group = getattr(self.params.cloudrig_parameters, 'root_parent_group'),
				layers = getattr(self.params.cloudrig_parameters, 'root_parent_layers')[:],
				preset = 8,
				defaults = self.defaults
			)
			self.root_parent = cloud_utils.create_parent_bone(self.root_bone, self.root_parent_set)
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

		# Create Bone Groups based on CloudRig Bone Sets.
		for rig in self.rig_list:
			if not hasattr(rig, 'bone_sets'): continue	# TODO: Rigify compatibility.
			for bone_set in rig.bone_sets:
				meta_bg = bone_set.ensure_bone_group(self.metarig, overwrite=False)
				if meta_bg:
					bone_set.normal = meta_bg.colors.normal[:]
					bone_set.select = meta_bg.colors.select[:]
					bone_set.active = meta_bg.colors.active[:]

				bone_set.ensure_bone_group(self.obj, overwrite=True)

	def ensure_widget_collection(self):
		""" Find or create the collection where rig widgets should be stored. """ # TODO: Rigify compatibility.
		wgt_collection = None
		coll_name = "widgets_" + self.obj.name.replace("RIG-", "").lower()

		# Try finding a "Widgets" collection next to the metarig.
		for c in self.metarig.users_collection:
			wgt_collection = c.children.get(coll_name)
			if wgt_collection: break

		if not wgt_collection:
			# Try finding a "Widgets" collection next to the generated rig.
			for c in self.obj.users_collection:
				wgt_collection = c.children.get(coll_name)
				if wgt_collection: break

		if not wgt_collection:
			# Create a Widgets collection within the master collection.
			wgt_collection = bpy.data.collections.new(coll_name)
			bpy.context.scene.collection.children.link(wgt_collection)
		
		wgt_collection.hide_viewport=True
		wgt_collection.hide_render=True
		return wgt_collection

	def load_widget(self, widget_name):
		return cloud_widgets.load_widget(widget_name, overwrite=self.params.rigify_force_widget_update, collection=self.wgt_collection)

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

			constraint_name = "Action_" + action.name
			do_symmetry = flip_name(subtarget)!=subtarget and act_def.symmetrical==True
			control_is_left_side = name_side_is_left(subtarget)

			# Adding action constraints to the bones
			for b in bones:
				constraints = []
				
				# If bone name is unflippable, but target bone name is flippable, split constraint in two.
				if flip_name(b.name) == b.name and do_symmetry:
					bone_is_left_side = name_side_is_left(b.name)

					# If bone name indicates a side, force subtarget to that side, if subtarget is flippable.
					if bone_is_left_side != control_is_left_side:
						subtarget = flip_name(subtarget)

					c_l = b.constraints.new(type='ACTION')
					c_l.name = constraint_name + ".L"
					c_l.influence = 0.5
					constraints.append(c_l)
					c_r = b.constraints.new(type='ACTION')
					c_r.influence = 0.5
					c_r.name = constraint_name + ".R"
					constraints.append(c_r)
				else:
					c = b.constraints.new(type='ACTION')
					c.name = constraint_name
					constraints.append(c)

				# Configure Action constraints
				for c in constraints:
					c.target_space = act_def.target_space
					c.transform_channel = act_def.transform_channel
					c.target = rig
					c.subtarget = subtarget
					c.action = action
					c.min = act_def.trans_min
					c.max = act_def.trans_max
					c.frame_start = act_def.frame_start
					c.frame_end = act_def.frame_end

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

		# Ensure it's transforms are cleared.
		backup_matrix = obj.matrix_world.copy()
		obj.matrix_world = Matrix()

		# Keep track of created widgets, so we can add them to Rigify-created Widgets collection at the end.
		self.wgt_collection = self.ensure_widget_collection()

		self.define_root_bone()
		
		# Rename metarig data (TODO: parameter)
		self.metarig.data.name = "Data_" + self.metarig.name

		# Enable all armature layers during generation. This is to make sure if you try to set a bone as active, it won't fail silently.
		obj.data.layers = [True]*32

		# Make sure X-Mirror editing is disabled, always!!
		obj.data.use_mirror_x = False

		# Get rid of anim data in case the rig already existed

		obj.animation_data_clear()
		obj.data.animation_data_clear()

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

		self.invoke_generate_bones()

		t.tick("Generate bones: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')
		bpy.ops.object.mode_set(mode='EDIT')

		self.invoke_parent_bones()

		if self.root_bone:
			self._Generator__parent_bones_to_root()

		t.tick("Parent bones: ")

		#------------------------------------------
		bpy.ops.object.mode_set(mode='OBJECT')

		self.ensure_bone_groups()

		for rig in self.rig_list:
			if not hasattr(rig, 'bone_sets'): continue
			for bone_set in rig.bone_sets:
				for bi in bone_set:
					pose_bone = obj.pose.bones.get(bi.name)
					if not pose_bone:
						print(f"Warning: BoneInfo {bi.name} wasn't created for some reason.")
						continue

					# Scale bone shape based on B-Bone scale
					bi.write_pose_data(pose_bone)
					if not pose_bone.use_custom_shape_bone_size:
						pose_bone.custom_shape_scale *= self.scale * bi.bbone_width * 10

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

		#TODO: For some reason when cloud_bone adds constraints to a bone, sometimes those constraints can be invalid even though they aren't actually.
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

def register():
	from bpy.utils import register_class
	register_class(CloudRigProperties)
	bpy.types.Armature.cloudrig_parameters = PointerProperty(type=CloudRigProperties)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CloudRigProperties)
	del bpy.types.Armature.cloudrig_parameters