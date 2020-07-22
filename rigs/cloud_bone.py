import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty

from rigify.base_rig import BaseRig, stage

from . import cloud_utils
from ..rigs.cloud_base import DefaultLayers
from ..utils.object import set_layers

"""TODO
Split up into cloud_tweak for the tweaking functionality, maybe one can extend the other idk.
Rework the entire thing so it uses BoneInfo instead of doing things normally? Not sure, should think about pros and cons.
"""

class Rig(BaseRig, cloud_utils.CloudUtilities):
	"""Create or tweak a single bone in the generated rig."""

	def find_org_bones(self, pose_bone):
		return pose_bone.name

	def initialize(self):
		super().initialize()
		self.bone_name = self.base_bone	# Name of the bone that is being created/modified.
		self.orgless_name = self.base_bone.replace("ORG-", "")
		self.copy_type = self.params.CR_bone_copy_type

		# If the metarig bone has a Child Of or Armature constraint, don't do any parenting logic.
		self.do_parenting = True
		meta_pose_bone = self.generator.metarig.pose.bones.get(self.orgless_name)
		for c in meta_pose_bone.constraints:
			if c.type in ('CHILD_OF', 'ARMATURE'):
				self.do_parenting = False
		
		self.create_deform_bone = meta_pose_bone.bone.use_deform

	def generate_bones(self):
		org_bone = self.get_bone(self.bones.org)
		meta_bone = self.generator.metarig.pose.bones.get(self.orgless_name)
		self.roll = org_bone.roll
		if self.copy_type == "Tweak":
			# Delete the Tweak ORG- bone. We will be copying stuff from the metarig bone instead.
			self.obj.data.edit_bones.remove(org_bone)
			self.bone_name = self.orgless_name

			self.params = meta_bone.rigify_parameters
		elif self.copy_type == "Create" and self.create_deform_bone:
			# Make a copy with DEF- prefix, as our deform bone.
			if meta_bone.bone.use_deform:
				print(f"Warning: Creating deform bone for {self.orgless_name} that's already set to use_deform=True.")
			def_bone_name = "DEF-" + self.orgless_name
			self.def_bone_name = self.copy_bone(org_bone.name, def_bone_name)
			def_bone = self.get_bone(self.def_bone_name)
			def_bone.bbone_x = def_bone.bbone_z = org_bone.bbone_x
			set_layers(def_bone, [DefaultLayers['DEF'].value])

	@stage.configure_bones
	def modify_bone_group(self):
		mod_bone = self.get_bone(self.bone_name)
		if self.copy_type == 'Tweak':
			# Since the ORG- bone got deleted during generate_bones, rename it to that name, to move any references from that ORG- bone over to the real bone.
			mod_bone.name = "ORG-"+mod_bone.name
			self.bone_name = self.base_bone

		meta_bone = self.generator.metarig.pose.bones.get(self.orgless_name)

		meta_bg = meta_bone.bone_group
		if self.copy_type=='Create' or self.params.CR_bone_group:
			if meta_bg:
				bg_name = meta_bg.name
				bg = self.obj.pose.bone_groups.get(bg_name)
				if not bg:
					bg = self.obj.pose.bone_groups.new(name=bg_name)
					bg.color_set = meta_bg.color_set
					bg.colors.normal = meta_bg.colors.normal[:]
					bg.colors.active = meta_bg.colors.active[:]
					bg.colors.select = meta_bg.colors.select[:]
				mod_bone.bone_group = bg

	@stage.apply_bones
	def modify_edit_bone(self):
		meta_bone = self.generator.metarig.data.bones.get(self.orgless_name)

		mod_bone = self.get_bone(self.bone_name)
		pose_bone = self.obj.pose.bones.get(mod_bone.name)

		if hasattr(self, "def_bone_name"):
			# TODO: Would this fail if I put it in generate_bones stage? I feel like that's where it started, and it would fail, but I don't really get why.
			def_bone = self.get_bone(self.def_bone_name)
			def_bone.parent = mod_bone

		parent_name = self.params.CR_bone_parent
		parent_bone = None
		if parent_name != "" and self.do_parenting:
			try:
				parent_bone = self.get_bone(parent_name)
				if parent_bone.bbone_segments == 1:
					mod_bone.parent = parent_bone
				else:
					mod_bone.parent = None # For parenting to bendy bones, we add Armature constraint in modify_pose_bone().
			except:
				print(f"Warning: Target parent bone {parent_name} not found for rig {self.base_bone}")

		if self.params.CR_bone_transforms:
			mod_bone.head = meta_bone.head_local.copy()
			mod_bone.tail = meta_bone.tail_local.copy()
			mod_bone.roll = self.roll
			mod_bone.bbone_x = meta_bone.bbone_x
			mod_bone.bbone_z = meta_bone.bbone_z
		
		# Rename the bone to its final name, without the ORG- prefix.
		self.bone_name = mod_bone.name = self.orgless_name

	def do_parenting_with_constraint(self):
		mod_bone = self.get_bone(self.bone_name)

		# Add parenting constraint
		parent_name = self.params.CR_bone_parent
		parent_bone = self.obj.pose.bones.get(parent_name)
		if parent_bone and parent_bone.bone.bbone_segments > 1:
			arm_con = mod_bone.constraints.new('ARMATURE')
			arm_con.name = "Armature@" + parent_name # Let relink_constraints() take care of setting up the constraint from here.
			arm_con.targets.new()

			# Move constraint to top of the stack.
			mod_bone.constraints.move(len(mod_bone.constraints)-1, 0)

	@stage.finalize
	def modify_pose_bone(self):	
		meta_bone = self.generator.metarig.pose.bones.get(self.orgless_name)
		mod_bone = self.get_bone(self.bone_name)

		if mod_bone.rotation_mode == 'QUATERNION':
			print(f"Warning: cloud_bone {meta_bone.name} was on Quaternion rotation mode. Forcing it to XYZ.")
			mod_bone.rotation_mode = 'XYZ'

		if self.copy_type == 'Create':
			self.do_parenting_with_constraint()
			for c in mod_bone.constraints:
				self.relink_constraint(c)
			return

		mod_bone.bone.use_deform = meta_bone.bone.use_deform

		if self.params.CR_bone_locks:
			mod_bone.lock_location = meta_bone.lock_location[:]
			mod_bone.lock_rotation = meta_bone.lock_rotation[:]
			mod_bone.lock_rotation_w = meta_bone.lock_rotation_w
			mod_bone.lock_scale = meta_bone.lock_scale[:]
		
		if self.params.CR_bone_rot_mode:
			mod_bone.rotation_mode = meta_bone.rotation_mode
		
		if self.params.CR_bone_shape:
			mod_bone.custom_shape = meta_bone.custom_shape
			mod_bone.custom_shape_scale = meta_bone.custom_shape_scale
			mod_bone.custom_shape_transform = meta_bone.custom_shape_transform
			mod_bone.use_custom_shape_bone_size = meta_bone.use_custom_shape_bone_size
			mod_bone.bone.show_wire = meta_bone.bone.show_wire
		
		if self.params.CR_bone_layers:
			mod_bone.bone.layers = meta_bone.bone.layers[:]
		
		if self.params.CR_bone_ik_settings:
			mod_bone.ik_stretch = meta_bone.ik_stretch
			mod_bone.lock_ik_x = meta_bone.lock_ik_x
			mod_bone.lock_ik_y = meta_bone.lock_ik_y
			mod_bone.lock_ik_z = meta_bone.lock_ik_z
			mod_bone.ik_stiffness_x = meta_bone.ik_stiffness_x
			mod_bone.ik_stiffness_y = meta_bone.ik_stiffness_y
			mod_bone.ik_stiffness_z = meta_bone.ik_stiffness_z
			mod_bone.use_ik_limit_x = meta_bone.use_ik_limit_x
			mod_bone.use_ik_limit_y = meta_bone.use_ik_limit_y
			mod_bone.use_ik_limit_z = meta_bone.use_ik_limit_z
			mod_bone.ik_min_x = meta_bone.ik_min_x
			mod_bone.ik_max_x = meta_bone.ik_max_x
			mod_bone.ik_min_y = meta_bone.ik_min_y
			mod_bone.ik_max_y = meta_bone.ik_max_y
			mod_bone.ik_min_z = meta_bone.ik_min_z
			mod_bone.ik_max_z = meta_bone.ik_max_z
		
		if self.params.CR_bone_bbone_props:
			mod_bone.bone.bbone_segments = meta_bone.bone.bbone_segments
			mod_bone.bone.bbone_x = meta_bone.bone.bbone_x
			mod_bone.bone.bbone_z = meta_bone.bone.bbone_z

		if not self.params.CR_bone_constraints_additive:
			while len(mod_bone.constraints)>1:
				mod_bone.constraints.remove(mod_bone.constraints[0])

		self.do_parenting_with_constraint()
		# Copy constraints from meta_bone to mod_bone
		for c in meta_bone.constraints:
			new_con = self.copy_constraint(c, mod_bone)

		# Relink constraints
		for c in mod_bone.constraints:
			self.relink_constraint(c)
		
		# Copy custom properties
		if self.params.CR_bone_props and '_RNA_UI' in meta_bone.keys():
			keys = [k for k in meta_bone.keys() if k not in ['_RNA_UI', 'rigify_parameters', 'rigify_type']]
			cloud_utils.copy_custom_properties(meta_bone, keys, mod_bone)

		# Copy and retarget drivers
		self.copy_and_relink_drivers(mod_bone)

	###############################
	# Utilities

	def copy_constraint(self, from_con, to_bone):
		new_con = to_bone.constraints.new(from_con.type)
		new_con.name = from_con.name

		skip = ['active', 'bl_rna', 'error_location', 'error_rotation', 'is_proxy_local', 'is_valid', 'rna_type', 'type']
		for key in dir(from_con):
			if "__" in key: continue
			if(key in skip): continue

			if key=='targets' and new_con.type=='ARMATURE':
				for t in from_con.targets:
					new_t = new_con.targets.new()
					new_t.target = t.target
					new_t.subtarget = t.subtarget
				continue

			value = getattr(from_con, key)
			try:
				setattr(new_con, key, value)
			except AttributeError:	# Read-Only properties throw AttributeError. These should all be added to the skip list.
				print(f"Warning: Can't copy read-only attribute {key} to {new_con.type} type constraint")
				continue
		
		return new_con

	def relink_constraint(self, constraint):
		""" Constraint re-linking is done similarly to Rigify, but without the prefix-only shorthand.
			Constraint names can contain an @ character which separates the constraint name from the desired target to set when all bones have been generated.
			Eg. "Transformation@FK-Spine" on meta_bone will result in a constraint on mod_bone called "Transformation" with "FK-Spine" as its subtarget.
			Armature constraints can have multiple @ targets.
		"""
		split_name = constraint.name.split("@")
		subtargets = split_name[1:]
		constraint.name = split_name[0]

		if constraint.type=='ARMATURE':
			# Ensure required number of targets
			for i in range(len(constraint.targets), len(subtargets)-1):
				constraint.targets.new()

			for i, t in enumerate(constraint.targets):
				t.target = self.obj
				t.subtarget = subtargets[i]
			return

		if not constraint.target:
			constraint.target = self.obj
		if len(subtargets) > 0:
			constraint.subtarget = subtargets[0]
		else:
			# This is allowed to happen with targetless constraints like Limit Location.
			pass

	def copy_and_relink_drivers(self, bone):
		"""Copy and retarget drivers from both the metarig Object and the metarig Data."""
		metarig = self.generator.metarig
		rig = self.obj
		if not metarig.animation_data: return

		for d in metarig.animation_data.drivers:
			if bone.name in d.data_path:
				self.copy_and_relink_driver(d, rig, d.data_path, d.array_index)

		if not metarig.data.animation_data: return
		for d in metarig.data.animation_data.drivers:
			if bone.name in d.data_path:
				self.copy_and_relink_driver(d, rig.data, d.data_path, d.array_index)

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_bone_constraints_additive = BoolProperty(
			name="Additive Constraints"
			,description="Add the constraints of this bone to the generated bone's constraints. When disabled, we replace the constraints instead"
			,default=True
		)

		params.CR_bone_copy_type = EnumProperty(
			name="Copy Type"
			,items=(
				("Create", "Create", "Create a new bone"),
				("Tweak", "Tweak", "Tweak an existing bone")
			)
			,description="Create: Create a standalone control (If one exists, overwrite it completely). Tweak: Find a control with the name of this bone, and overwrite it only partially"
			,default="Create"
		)

		# Parameters for tweaking existing bone
		params.CR_bone_parent = StringProperty(
			 name="Parent"
			,description="When this is not an empty string, set the parent to the bone with this name"
			,default=""
		)
		params.CR_bone_transforms = BoolProperty(
			 name="Transforms"
			,description="Replace the matching generated bone's transforms with this bone's transforms" # An idea: when this is False, let the generation script affect the metarig - and move this bone, to where it is in the generated rig.
			,default=False
		)
		params.CR_bone_locks = BoolProperty(
			 name="Locks"
			,description="Replace the matching generated bone's transform locks with this bone's transform locks"
			,default=True
		)
		params.CR_bone_rot_mode = BoolProperty(
			 name="Rotation Mode"
			,description="Set the matching generated bone's rotation mode to this bone's rotation mode"
			,default=False
		)
		params.CR_bone_shape = BoolProperty(
			 name="Bone Shape"
			,description = "Replace the matching generated bone's shape with this bone's shape"
			,default=False
		)
		params.CR_bone_group = BoolProperty(
			 name="Bone Group"
			,description="Replace the matching generated bone's group with this bone's group"
			,default=False
		)
		params.CR_bone_layers = BoolProperty(
			 name="Layers"
			,description="Set the generated bone's layers to this bone's layers"
			,default=False
		)
		params.CR_bone_props = BoolProperty(
			 name="Custom Properties"
			,description="Copy custom properties from this bone to the generated bone"
			,default=False
		)
		params.CR_bone_ik_settings = BoolProperty(
			 name="IK Settings"
			,description="Copy IK settings from this bone to the generated bone"
			,default=False
		)
		params.CR_bone_bbone_props = BoolProperty(
			name="B-Bone Settings"
			,description="Copy B-Bone settings from this bone to the generated bone"
			,default=False
		)

	@classmethod
	def parameters_ui(cls, layout, params):
		"""Create the ui for the rig parameters."""
		from ..ui import ui_label_with_linebreak
		ui_label_with_linebreak(layout, cls.__doc__)

		layout.use_property_split = True
		
		pb = bpy.context.active_pose_bone

		layout.prop(params, "CR_bone_parent")
		layout.row().prop(params, "CR_bone_copy_type", expand=True, text="Copy Type")
		row = layout.row()
		col1 = row.column()
		col2 = row.column()	# Empty column for indent
		if params.CR_bone_copy_type=='Tweak':
			col1.prop(params, "CR_bone_constraints_additive")
			col1.prop(params, "CR_bone_transforms")
			col1.prop(params, "CR_bone_locks")
			col1.prop(params, "CR_bone_rot_mode")
			col1.prop(params, "CR_bone_shape")
			col1.prop(params, "CR_bone_group")
			col1.prop(params, "CR_bone_layers")
			col1.prop(params, "CR_bone_props")
			col1.prop(params, "CR_bone_ik_settings")
			col1.prop(params, "CR_bone_bbone_props")
		else:
			col1.prop(pb.bone, "use_deform", text="Create Deform Bone")

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_bone")