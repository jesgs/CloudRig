from typing import Optional

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from mathutils import Vector

from ..bone import BoneInfo
from .cloud_base import CloudBaseRig

from .. import widgets as cloud_widgets
from ..utils.maths import bounding_box_center, flat

class CloudAimRig(CloudBaseRig):
	"""Create aim target controls for a single bone."""

	use_custom_props = True

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.group_mstr_set = self.ensure_bone_set("Aim Group Target Controls")
		self.target_ctrl = self.ensure_bone_set("Aim Target Controls")
		self.aim_mch = self.ensure_bone_set("Aim Target Mechanism")
		if self.params.CR_aim_deform:
			self.aim_def = self.ensure_bone_set("Aim Deform")

	def create_bone_infos(self):
		super().create_bone_infos()

		aim_org = self.org_chain[0]
		aim_bone = self.make_aim_helper(aim_org)

		if self.params.CR_aim_root:
			self.aim_root = self.make_root_bone(aim_org)
		self.group_master = None
		if self.params.CR_aim_group!="":
			self.group_master = self.ensure_group_master()
		self.ctr_bone = self.make_aim_control(aim_org, aim_bone)
		target_bone = self.make_target_control(aim_bone, self.group_master)

		aim_bone.add_constraint('DAMPED_TRACK'
			,subtarget = target_bone.name
		)

		if self.params.CR_aim_deform:
			self.make_def_bone(self.ctr_bone, self.aim_def)

		if self.params.CR_aim_eye_highlight:
			self.create_eye_highlight(self.ctr_bone)

	def find_target_pos(self, bone) -> Vector:
		"""Find location of where the target bone should be for an aim bone."""
		if self.params.CR_aim_flatten:
			direction = bone.vector.normalized()
			# Ignore X axis
			direction[0] = 0.0
			return bone.head + direction * self.params.CR_aim_target_distance * self.scale
		else:
			return bone.tail + bone.vector.normalized() * self.params.CR_aim_target_distance * self.scale

	def make_target_control(self, bone, parent=None) -> BoneInfo:
		"""Set up target control for a bone"""
		if not parent:
			parent = bone.parent

		head = self.find_target_pos(bone)
		bpy.context.scene.cursor.location = head.copy()
		tail = head + bone.vector.normalized() * self.scale/5

		target_bone = self.target_ctrl.new(
			name	= self.org_chain[0].name.replace("ORG", "TGT")
			,source = self.org_chain[0]
			,head	= head
			,tail	= tail
			,custom_shape = self.ensure_widget("Circle")
			,parent = parent
		)
		dsp_bone = self.create_dsp_bone(target_bone)
		dsp_bone.add_constraint('DAMPED_TRACK', subtarget=bone.name, track_axis='TRACK_NEGATIVE_Y')

		return target_bone

	def make_aim_helper(self, org_bone) -> BoneInfo:
		"""Create an AIM helper for @org_bone targetting @target_bone, while leaving
		   @org_bone free to rotate.
		"""
		aim_bone = self.aim_mch.new(
			name		 = self.org_chain[0].name.replace("ORG", "AIM")
			,source		 = org_bone
			,hide_select = self.mch_disable_select
			,parent		 = org_bone
		)
		# if self.params.CR_aim_flatten:
			# aim_bone.flatten()
		return aim_bone

	def make_aim_control(self, org_bone, aim_bone) -> BoneInfo:
		"""Create direct control, with a display bone at the tip of it."""
		ctr_bone = self.target_ctrl.new(
			name = self.naming.make_name(["CTR"], *self.naming.slice_name(org_bone.name)[1:])
			,source = org_bone
			,parent = org_bone
			,custom_shape = self.ensure_widget("Circle")
		)

		ctr_bone.add_constraint('COPY_ROTATION'
			,subtarget = aim_bone.name
		)

		# Lock all location and Y scale
		self.lock_transforms(ctr_bone, loc=True, rot=False, scale=[False, True, False])

		# Scale hack! Don't actually allow scaling the control bone, 
		# but send the scaling input into the display bone's scale, so it appears like it is scaling.
		# This is done because actually scaling the bone would result in scaling the eyeball which is not useful
		# but this way we can hook up the scale to iris scaling shape keys.
		ctr_bone.add_constraint('LIMIT_SCALE'
			,use_min_x = True, use_min_y = True, use_min_z = True
			,use_max_x = True, use_max_y = True, use_max_z = True
			,min_x = 1, min_y = 1, min_z = 1
			,max_x = 1, max_y = 1, max_z = 1
			,use_transform_limit = False
			,space = 'LOCAL'
		)
		dsp_bone = self.create_dsp_bone(ctr_bone)
		dsp_bone.put(ctr_bone.tail)
		dsp_bone.drivers.append({
			'prop' : 'scale'
			,'index' : 0
			,'variables' : [(ctr_bone.name, '.scale[0]')]
		})
		dsp_bone.drivers.append({
			'prop' : '.scale'
			,'index' : 2
			,'variables' : [(ctr_bone.name, '.scale[2]')]
		})
		return ctr_bone

	def make_root_bone(self, bone) -> BoneInfo:
		base_bone = self.org_chain[0]
		root_bone = self.target_ctrl.new(
			name = base_bone.name.replace("ORG", "ROOT")
			,source = base_bone
			,parent = base_bone.parent
			,custom_shape = self.ensure_widget('Square')
			,custom_shape_scale = 2
		)
		root_dsp = self.create_dsp_bone(root_bone)
		root_dsp.put(self.org_chain[0].tail)

		bone.parent = root_bone

		if self.rigify_parent:
			self.rigify_parent.reparent_bone(root_bone)
		return root_bone

	def create_eye_highlight(self, ctr_bone):
		name_slices = self.naming.slice_name(ctr_bone)
		name_slices[1] += "_Highlight"
		highlight_ctr = self.target_ctrl.new(
			name = self.naming.make_name(*name_slices)
			,source = ctr_bone
			,parent = ctr_bone
			,custom_shape = self.ensure_widget("Circle")
			,length = ctr_bone.length/5
			,custom_shape_scale = ctr_bone.custom_shape_scale/3
		)
		self.lock_transforms(highlight_ctr, loc=True, rot=False, scale=[False, True, False])
		highlight_dsp = self.create_dsp_bone(highlight_ctr)
		highlight_dsp.put(ctr_bone.tail)
		self.make_def_bone(highlight_ctr, self.aim_def)

	def apply_custom_root_parent(self, bone=None, parent_name=""):
		"""Overrides cloud_base to do nothing."""
		pass

	def ensure_group_master(self) -> Optional[BoneInfo]:
		"""This function will be called by each aim rig, but we want to make sure
		   it only runs once per aim group.
		"""

		# Check if a bone with the right name already exists and if it does, just return it.
		group_name = self.params.CR_aim_group
		group_master_name = "MSTR-TGT-"+group_name
		existing = self.generator.find_bone_info(group_master_name)
		if existing:
			return existing

		# Collect all cloud_aim rigs in this group.
		aim_bones = []
		first_parent = ""
		for rig in self.generator.rig_list:
			if isinstance(rig, CloudAimRig) and rig.params.CR_aim_group == group_name:
				aim_bone = self.obj.pose.bones[rig.base_bone]
				aim_bones.append(aim_bone)
				if aim_bone.parent and first_parent=="":
					first_parent = aim_bone.parent.name

		if len(aim_bones) < 2:
			return None

		# Find center of all aim bones
		aims_center = bounding_box_center([b.head for b in aim_bones])

		# Find center of all targets
		target_positions = [self.find_target_pos(b) for b in aim_bones]
		target_center = bounding_box_center(target_positions)

		# Create a helper bone in the center.
		group_vec = target_center - aims_center
		center_bone = self.aim_mch.new(
			name = "CEN-"+group_name
			,head = aims_center
			,tail = aims_center + group_vec.normalized() * self.scale/10
			,bbone_width = 0.1
			,parent = self.generator.find_bone_info(first_parent)
		)

		# Create the master bone.
		group_master = self.group_mstr_set.new(
			name = group_master_name
			,head = target_center
			,tail = target_center - group_vec.normalized()*self.scale/10
			,bbone_width = 0.1
		)
		group_master.add_constraint('DAMPED_TRACK'
			,subtarget = center_bone.name
		)

		group_widget = cloud_widgets.bezier_widget(self, target_positions, group_master)
		group_master.custom_shape = group_widget
		group_master.custom_shape_scale = 1/self.scale

		return group_master

	def apply_parent_switching(self,
			child_bone=None,
			prop_bone=None, prop_name="",
			ui_area="misc_settings", row_name="", col_name=""
		):
		"""Overrides cloud_base to apply the parent switching to the aim target 
		or group master if it exists."""
		control_bone = self.group_master
		if not control_bone:
			control_bone = self.ctr_bone
		else:
			# Ensure parent switching for the group master
			if self.group_master.parent and self.group_master.parent.name == "Parents_"+self.group_master.name:
				# If the parent switching set-up already exists, don't create it again.
				return
		super().apply_parent_switching(
			child_bone = control_bone
			,prop_bone = self.properties_bone
			,ui_area = 'face_settings'
			,col_name = self.params.CR_aim_group + " Parent"
		)

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Aim Group Target Controls", preset=1,	default_layers=[cls.default_layers('FK_MAIN')])
		cls.define_bone_set(params, "Aim Target Controls", 		 preset=2,	default_layers=[cls.default_layers('FK_MAIN')])
		cls.define_bone_set(params, "Aim Target Mechanism",					default_layers=[cls.default_layers('MCH')], override='MCH')
		if params.CR_aim_deform:
			cls.define_bone_set(params, "Aim Deform",						default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""

		params.CR_aim_show_settings = BoolProperty(name="Aim Settings")

		params.CR_aim_group = StringProperty(
			name		 = "Aim Group"
			,default	 = "Eyes"
			,description = "Aim rigs belonging to the same Aim Group will have a shared master control generated for them"
		)

		params.CR_aim_target_distance = FloatProperty(
			name		 = "Target Distance"
			,default	 = 5.0
			,description = "Distance of the target from the aim bone. This value is not in blender units, but is a value relative to the scale of the rig"
			,min		 = 0
		)
		params.CR_aim_flatten = BoolProperty(
			name		 = "Flatten X"
			,description = "Discard the X component of the eye vector when placing the target control. Useful for eyes that have significant default rotation. This can result in the eye becoming cross-eyed in the default pose, but it prevents the eye targets from crossing each other or being too far from each other"
			,default	 = False
		)
		# TODO: Do this the same way as cloud_copy instead, ie. use the bone's use_deform property.
		params.CR_aim_deform = BoolProperty(
			name		 = "Create Deform"
			,default	 = False
			,description = "Create a deform bone for this rig"
		)
		# TODO: Move this to cloud_base.
		params.CR_aim_root = BoolProperty(
			name		 = "Create Root"
			,default	 = False
			,description = "Create a root bone for this rig"
		)
		params.CR_aim_eye_highlight = BoolProperty(
			name		 = "Create Sub-Control"
			,description = "Create a secondary control and deform bone attached to the aim control. Useful for eye highlights"
			,default	 = False
		)
		super().add_parameters(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_aim_show_settings"): return layout

		ob = bpy.context.object

		cls.draw_prop(layout, params, "CR_aim_group")
		cls.draw_prop(layout, params, "CR_aim_target_distance")
		cls.draw_prop(layout, params, "CR_aim_flatten")
		cls.draw_prop(layout, params, "CR_aim_deform")
		cls.draw_prop(layout, params, "CR_aim_root")
		cls.draw_prop(layout, params, "CR_aim_eye_highlight")

		return layout

class Rig(CloudAimRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)