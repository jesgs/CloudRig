from typing import Optional

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from mathutils import Vector

from ..bone import BoneInfo
from .cloud_base import CloudBaseRig

from .. import widgets as cloud_widgets
from ..utils.maths import bounding_box_center

class CloudAimRig(CloudBaseRig):
	"""Create aim target controls for a single bone."""

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

		if self.params.CR_aim_root:
			self.aim_root = self.make_aim_root(aim_org) # TODO: This might as well be a call to self.make_parent_control(), no?
		self.group_master = self.ensure_group_master()
		self.ctr_bone = self.make_aim_control(aim_org)
		target_bone = self.make_target_control(self.ctr_bone, self.group_master)
		aim_bone = self.make_aim_helper(self.ctr_bone, target_bone)
		if self.params.CR_aim_deform:
			self.make_def_bone(aim_org, self.aim_def)

	def find_target_pos(self, bone) -> Vector:
		"""Find location of where the target bone should be for an aim bone."""
		return bone.tail + bone.vector.normalized() * self.params.CR_aim_target_distance * self.scale

	def make_target_control(self, bone, parent=None) -> BoneInfo:
		"""Set up target control for a bone"""
		if not parent:
			parent = bone.parent

		head = self.find_target_pos(bone)
		tail = head + bone.vector.normalized() * self.scale/5

		target_bone = self.target_ctrl.new(
			name	= self.org_chain[0].name.replace("ORG", "TGT")
			,source = self.org_chain[0]
			,head	= head
			,tail	= tail
			,custom_shape = self.ensure_widget("Oval")
			,parent = parent
		)
		dsp_bone = self.create_dsp_bone(target_bone)
		dsp_bone.add_constraint('DAMPED_TRACK', subtarget=bone.name, track_axis='TRACK_NEGATIVE_Y')

		return target_bone

	def make_aim_helper(self, bone, target_bone) -> BoneInfo:
		"""Create an AIM helper for @bone targetting @target_bone, while leaving
		   @bone free to rotate.
		"""
		aim_bone = self.aim_mch.new(
			name		 = self.org_chain[0].name.replace("ORG", "AIM")
			,source		 = bone
			,hide_select = self.mch_disable_select
			,parent		 = bone.parent
		)
		bone.parent = aim_bone
		aim_bone.add_constraint('DAMPED_TRACK'
			,subtarget = target_bone.name
		)
		return aim_bone

	def make_aim_control(self, bone) -> BoneInfo:
		"""Create direct control, with a display bone that is aim radius away towards the bone's +Y axis."""
		ctr_bone = self.target_ctrl.new(
			name = self.naming.make_name(["CTR"], *self.naming.slice_name(bone.name)[1:])
			,source = bone
			,parent = bone.parent
			,custom_shape = self.ensure_widget("Oval")
		)
		# We parent ORG with transform constraint because we want to use the local transform matrix for reading its rotation.
		bone.add_constraint('COPY_TRANSFORMS'
			,subtarget = ctr_bone.name
			,space = 'WORLD'
			,mix_mode = 'REPLACE'
		)
		dsp_bone = self.create_dsp_bone(ctr_bone)
		dsp_bone.put(ctr_bone.tail)
		return ctr_bone

	def make_aim_root(self, bone) -> BoneInfo:
		# TODO: Root bone should be bigger and have a DSP- bone in the same place as the CTR bone.
		base_bone = self.org_chain[0]
		root_bone = self.target_ctrl.new(
			name = base_bone.name.replace("ORG", "ROOT")
			,source = base_bone
			,parent = base_bone.parent
			,custom_shape = self.ensure_widget('Square')
			,custom_shape_scale = 2
		)
		bone.parent = root_bone
		
		if self.rigify_parent:
			self.rigify_parent.reparent_bone(root_bone)
		return root_bone

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
		"""Overrides cloud_base."""
		# Ensure parent switching for the group master
		if self.group_master.parent and self.group_master.parent.name == "Parents_"+self.group_master.name:
			# If the parent switching set-up already exists, don't create it again.
			return
		super().apply_parent_switching(
			child_bone = self.group_master
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

		super().add_parameters(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_aim_show_settings"): return layout

		ob = bpy.context.object

		cls.draw_prop(layout, params, "CR_aim_group")
		cls.draw_prop(layout, params, "CR_aim_target_distance")
		cls.draw_prop(layout, params, "CR_aim_deform")
		cls.draw_prop(layout, params, "CR_aim_root")

		return layout

class Rig(CloudAimRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)