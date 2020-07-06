import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from mathutils import Vector

from .cloud_utils import make_name, slice_name
from .cloud_base import CloudBaseRig
from .. import widgets as cloud_widgets
from ..utils import bounding_box_center

class CloudEyeRig(CloudBaseRig):
	"""Create aim target controls for a single bone."""

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		self.category = self.slice_name(self.base_bone)[1]
		if self.params.CR_use_custom_category_name:
			self.category = self.params.CR_custom_category_name
		
		self.limb_name = self.category
		if self.params.CR_use_custom_limb_name:
			self.limb_name = self.params.CR_custom_limb_name		# Name used for naming bones. Should not contain a side identifier like .L/.R.
		self.limb_ui_name = self.side_prefix + " " + self.limb_name	# Name used for UI related things. Should contain the side identifier.

		self.limb_name_props = self.limb_ui_name.replace(" ", "_").lower()
		self.fk_hinge_name = "fk_hinge_" + self.limb_name_props

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.group_mstr_set = self.ensure_bone_set("Eye Group Target Controls")
		self.target_ctrl = self.ensure_bone_set("Eye Target Controls")
		self.eye_mch = self.ensure_bone_set("Eye Target Mechanism")
		self.eye_def = self.ensure_bone_set("Eye Deform")

	def prepare_bones(self):
		super().prepare_bones()

		eye_org = self.org_chain[0]

		if self.params.CR_eye_root:
			self.make_eye_root(eye_org)
		group_master = self.ensure_group_master()
		target_bone = self.make_target_control(eye_org, group_master)
		aim_bone = self.make_aim_helper(eye_org, target_bone)
		self.make_eye_control(eye_org)
		if self.params.CR_eye_deform:
			self.make_def_bone(eye_org, self.eye_def)

	def find_target_pos(self, bone):
		"""Find location of where the target bone should be for an eye bone."""
		return bone.tail + bone.vector.normalized() * self.params.CR_eye_target_distance * self.scale

	def make_target_control(self, bone, parent=None):
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
			,custom_shape = self.load_widget("Oval")
			,parent = parent
		)
		dsp_bone = self.create_dsp_bone(target_bone)
		dsp_bone.add_constraint('DAMPED_TRACK', subtarget=bone.name, track_axis='TRACK_NEGATIVE_Y')

		return target_bone

	def make_aim_helper(self, bone, target_bone):
		"""Create an aim bone for bone targetting target_bone, while leaving bone free to rotate."""
		aim_bone = self.eye_mch.new(
			name		 = bone.name.replace("ORG", "AIM")
			,source		 = bone
			,hide_select = self.mch_disable_select
			,parent		 = bone.parent
		)
		bone.parent = aim_bone
		aim_bone.add_constraint('DAMPED_TRACK'
			,subtarget = target_bone.name
		)
		return aim_bone

	def make_eye_control(self, bone):
		"""Create direct control for an eye, with a display bone that is eye radius away towards the bone's +Y axis."""
		ctr_bone = self.target_ctrl.new(
			name = make_name(["CTR"], *slice_name(bone.name)[1:])
			,source = bone
			,parent = bone.parent
			,custom_shape = self.load_widget("Oval")
		)
		bone.parent = ctr_bone
		dsp_bone = self.create_dsp_bone(ctr_bone)
		dsp_bone.put(ctr_bone.tail)
		return ctr_bone

	def make_eye_root(self, bone):
		base_bone = self.org_chain[0]
		root_bone = self.target_ctrl.new(
			name = base_bone.name.replace("ORG", "ROOT")
			,source = base_bone
			,parent = base_bone.parent
			,custom_shape = self.load_widget('Square')
		)
		bone.parent = root_bone

	def ensure_group_master(self):
		# At the moment, this function will be called by each eye bone, but we want to make sure it only runs once per group.
		# So check if a bone with the right name already exists and if it does, just return it.

		group_name = self.params.CR_eye_group
		group_master_name = "MSTR-TGT-"+group_name

		existing = self.generator.find_bone_info(group_master_name)
		if existing: 
			return existing

		# Collect all cloud_eye rigs in this group.
		eye_bones = []
		for b in self.obj.pose.bones:
			if b.rigify_type == 'cloud_eye' and b.rigify_parameters.CR_eye_group == self.params.CR_eye_group:
				eye_bones.append(b)

		if len(eye_bones) < 2:
			return

		# Center of all eyes
		eyes_center = bounding_box_center([b.head for b in eye_bones])

		# Center of targets
		target_positions = [self.find_target_pos(b) for b in eye_bones]
		target_center = bounding_box_center(target_positions)

		# Create a helper bone in the center.
		group_vec = target_center - eyes_center
		center_bone = self.eye_mch.new(
			name = "CEN-"+group_name
			,head = eyes_center
			,tail = eyes_center + group_vec.normalized() * self.scale/10
			,bbone_width = 0.1
			,parent = eye_bones[0].parent
		)

		# TODO: Not sure how to address the case where eye rigs in the same Eye Group might be parented to different bones.
		for eb in eye_bones:
			if eb.parent != eye_bones[0].parent:
				print(f"Warning: Eye bones in the same group having different parents is not fully supported. {group_master_name} will be parented arbitrarily to {eye_bones[0].parent}!")

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

		# Parent switching
		eye_group_parents_prop_name = "eye_group_parents_" + group_name.lower()
		search_parents = ["Root", "Torso", "Chest", "Neck", "Head"]
		parent_names = self.rig_child(group_master, search_parents, self.ikfk_properties_bone, eye_group_parents_prop_name)
		if len(parent_names) > 0:
			info = {
				"prop_bone" : self.ikfk_properties_bone.name,
				"prop_id" : eye_group_parents_prop_name,
				"texts" : parent_names,

				"operator" : "pose.cloudrig_switch_parent",
				"icon" : "COLLAPSEMENU",
				"parent_names" : parent_names,
				"bones" : [group_master.name],
				}
			self.add_ui_data("face_settings", self.params.CR_eye_group, self.params.CR_eye_group, info, default=0, _max=len(parent_names)-1)

		return group_master

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Eye Group Target Controls", preset=1,	default_layers=[cls.default_layers('FK_MAIN')])
		cls.define_bone_set(params, "Eye Target Controls", 		 preset=2,	default_layers=[cls.default_layers('FK_MAIN')])
		cls.define_bone_set(params, "Eye Target Mechanism",					default_layers=[cls.default_layers('MCH')], override='MCH')
		if params.CR_eye_deform:
			cls.define_bone_set(params, "Eye Deform",						default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""

		params.CR_eye_show_settings = BoolProperty(name="Eye Rig")

		params.CR_eye_group = StringProperty(
			name		 = "Eye Group"
			,default	 = "Eyes"
			,description = "Eye rigs belonging to the same Eye Group will have a shared master control generated for them"
		)

		params.CR_eye_target_distance = FloatProperty(
			name		 = "Target Distance"
			,default	 = 5.0
			,description = "Distance of the target from the eye. This value is not in blender units, but is a value relative to the scale of the rig"
            ,min         = 0
		)
		params.CR_eye_deform = BoolProperty(
			name		 = "Create Deform"
			,default	 = False
			,description = "Create a deform bone for this rig. Not always needed, as you can simply object-parent your eye object to the ORG bone"
		)
		params.CR_eye_root = BoolProperty(
			name		 = "Create Root"
			,default	 = False
			,description = "Create a root bone for this rig."
		)

		super().add_parameters(params)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		ui_rows = super().cloud_params_ui(layout, params)

		icon = 'TRIA_DOWN' if params.CR_eye_show_settings else 'TRIA_RIGHT'
		layout.prop(params, "CR_eye_show_settings", toggle=True, icon=icon)
		if not params.CR_eye_show_settings: return ui_rows

		layout.prop(params, "CR_eye_group")
		layout.prop(params, "CR_eye_target_distance")
		layout.prop(params, "CR_eye_deform")
		layout.prop(params, "CR_eye_root")

		return ui_rows

class Rig(CloudEyeRig):
	pass