"""
Eye Track
    A rig that sets up an eye target thingie.
        The bone that holds the rig is the eye bone itself. The target is created some distance in front of it (along local Y axis)
        params:
            - Target group - all Eye rigs with the same Target Group will have a shared parent control, whose name will be based on this parameter, and location and bone shape based on the average location of the look targets in the group.
            - Target distance - how far in front the eye target should be created. (The units will be quite arbitrary since I do want to apply rig scale on this, so just mention that in the tooltip.)
    
    Bones:
    AIM-Eye: Damped Track constraint, a mechanism bone.
        CTR-Eye: No constraints, an exposed control.
            ORG-Eye: No constraints, an org bone.
            DEF-Eye: No constraints, a deform bone. (Might be worth adding a checkbox for creating this, as some people might want to object-parent their eyes)
    
    TGT-EyeGroup: No constraints, an exposed control that the eyes look at. Has a parent switcher with Armature constraint, for all parents registered for all eye rigs that belong to this EyeGroup.
        DSP-EyeGroup: Damped track to the parent of the eye? No, to the average position of all eyes in the group. May be tricky to keep track of that data...
        TGT-Eye: No constraints, an exposed control that ONE eye looks at.
            DSP-Eye: Damped track to the ORG bone.
    
    In many cases we will probably want bones going from the center of the eye to the eyelids, but those should probably simply be separate cloud_bone rigs because the constraints on these bones would need to be tweaked individually anyways.
"""

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

	def prepare_bones(self):
		super().prepare_bones()

		eye_org = self.org_chain[0]

		self.group_master = self.ensure_group_master()
		self.target_bone = self.make_target_control(eye_org)
		self.make_aim_helper(eye_org, self.target_bone)
	
	def find_target_pos(self, eye_bone):
		return eye_bone.tail + eye_bone.vector.normalized() * self.params.CR_eye_target_distance * self.scale

	def make_target_control(self, eye_bone):
		# Determine head and tail by projecting the eye bone along its +Y axis.
		head = self.find_target_pos(eye_bone)
		tail = head + eye_bone.vector.normalized() * self.scale/5

		target_bone = self.target_ctrl.new(
			name	= self.org_chain[0].name.replace("ORG", "TGT")
			,source = self.org_chain[0]
			,head	= head
			,tail	= tail
			,custom_shape = self.load_widget("Oval")
			,parent = self.group_master
			# TODO: bone shape, DSP bone, parent
		)
		return target_bone

	def make_aim_helper(self, org_bone, target_bone):
		aim_bone = self.eye_mch.new(
			name		 = org_bone.name.replace("ORG", "AIM")
			,source		 = org_bone
			,hide_select = self.mch_disable_select
			,parent		 = org_bone.parent
		)
		org_bone.parent = aim_bone
		aim_bone.add_constraint('DAMPED_TRACK'
			,subtarget = target_bone.name
		)

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
		for b in self.generator.metarig.pose.bones:
			if b.rigify_type == 'cloud_eye' and b.rigify_parameters.CR_eye_group == self.params.CR_eye_group:
				eye_bones.append(b)

		# Center of all eyes
		eyes_center = bounding_box_center([b.head for b in eye_bones])

		# Center of targets
		target_positions = [self.find_target_pos(b) for b in eye_bones]
		target_center = bounding_box_center(target_positions)

		# Create a helper bone in the center.
		group_vec = target_center - eyes_center
		group_center = self.eye_mch.new(
			name = "CEN-"+group_name
			,head = eyes_center
			,tail = eyes_center + group_vec.normalized() * self.scale/10
			,bbone_width = 0.1
		)

		# Create the master bone.
		group_master = self.group_mstr_set.new(
			name = group_master_name
			,head = target_center
			,tail = target_center - group_vec.normalized()*self.scale/10
			,bbone_width = 0.1
		)
		group_master.add_constraint('DAMPED_TRACK'
			,subtarget = group_center.name
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

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""

		params.CR_eye_show_settings = BoolProperty(name="Eye Rig")

		params.CR_eye_group = StringProperty(
			name		 = "Eye Group"
			,default	 = "Eye"
			,description = "Eye rigs belonging to the same Eye Group will have a shared master control generated for them"
		)

		params.CR_eye_target_distance = FloatProperty(
			name		 = "Target Distance"
			,default	 = 1.0
			,description = "Distance of the target from the eye. This value is not in blender units, but is a value relative to the scale of the rig"
            ,min         = 0
		)
		params.CR_eye_radius = FloatProperty(
			name		 = "Eye radius"
			,default	 = 0.01
			,description = "Radius of the eye. Only used for placing widgets correctly, has no mechanical effect. This value is not in blender units, but is a value relative to the scale of the rig"
            ,min         = 0
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

		return ui_rows

class Rig(CloudEyeRig):
	pass