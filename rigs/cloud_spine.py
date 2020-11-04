from bpy.props import BoolProperty
from mathutils import Vector

from .cloud_fk_chain import CloudFKChainRig

"""TODO
Re-implement FK-C bones (maybe under a param)
	Their values would probably have to be dependent on the length of the bone. Ie, a long bone should slide more when it's rotated, compared to a short bone.

Bug: IK-CTR-Chest flies away when moving the chest master far, needs a DSP- bone?
"""

class CloudSpineRig(CloudFKChainRig):
	"""Spine setup with FK, IK-like and stretchy IK controls. Currently only one of these per rig is supported."""

	forced_params = {
		'CR_chain_segments' : 1
		,'CR_fk_chain_double_first' : False
		,'CR_fk_chain_hinge' : False
		,'CR_fk_chain_display_center' : False
		,'CR_fk_chain_root' : True
	}

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		assert len(self.bones.org.main) > 2, "Spine must consist of at least 3 connected bones."

		# UI Strings and Custom Property names
		self.category = self.naming.strip_org(self.base_bone)
		if self.params.CR_fk_chain_use_category_name:
			self.category = self.params.CR_fk_chain_category_name

		self.spine_name = "Spine"
		if self.params.CR_fk_chain_use_limb_name:
			self.spine_name = self.params.CR_fk_chain_limb_name.replace(" ", "_")
		
		self.ik_prop_name = "ik_" + self.spine_name.lower()
		self.ik_stretch_name = "ik_stretch_" + self.spine_name.lower()

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.spine_main			= self.ensure_bone_set("Spine Main Controls")
		self.spine_parent_ctrls	= self.ensure_bone_set("Spine Parent Controls")
		self.spine_ik_secondary	= self.ensure_bone_set("Spine IK Secondary")
		self.spine_mch			= self.ensure_bone_set("Spine Mechanism")

	def prepare_bones(self):
		super().prepare_bones()

		if self.params.CR_spine_use_ik:
			self.make_ik_spine()
		self.tweak_str_spine()

		self.register_parents()

	def make_root_bone(self):
		"""Overrides."""

		# Create Troso Master control
		limb_root_bone = self.new_bonei(self.spine_main
			,name 		  = f"MSTR-{self.spine_name}_Torso"
			,parent		  = self.root_bone
			,source 	  = self.org_chain[0]
			,head 		  = self.org_chain[0].center
			,custom_shape = self.ensure_widget("Torso_Master")
		)
		return limb_root_bone

	def make_fk_chain(self):
		"""Overrides."""
		super().make_fk_chain()

		# Create master hip control
		self.mstr_hips = self.new_bonei(self.spine_main
				,name				= f"MSTR-{self.spine_name}_Hips"
				,source				= self.org_chain[0]
				,head				= self.org_chain[0].center
				,custom_shape 		= self.ensure_widget("Hips")
				,custom_shape_scale	= 0.7
				,parent				= self.limb_root_bone
		)
		self.limb_root_bone.flatten()
		if self.params.CR_spine_double:
			double_mstr_pelvis = self.create_parent_bone(self.limb_root_bone, self.spine_parent_ctrls)

		# Shift FK controls to their center.
		for fk_bone in self.fk_chain:
			fk_bone.head = fk_bone.center
			if fk_bone.prev:
				fk_bone.prev.tail = fk_bone.head

		# Parent the first one to MSTR-Torso.
		self.fk_chain[0].parent = self.limb_root_bone

	def make_ik_spine(self):
		### Create master chest control
		self.mstr_chest = self.new_bonei(self.spine_main
				,name				= f"MSTR-{self.spine_name}_Chest"
				,source 			= self.org_chain[-2]
				,head				= self.org_chain[-2].center
				,tail 				= self.org_chain[-2].center + Vector((0, 0, self.scale))
				,custom_shape 		= self.ensure_widget("Chest_Master")
				,custom_shape_scale = 0.7
				,parent				= self.limb_root_bone
			)

		if self.params.CR_spine_double:
			double_mstr_chest = self.create_parent_bone(self.mstr_chest, self.spine_parent_ctrls)

		self.mstr_hips.flatten()

		### IK Control (IK-CTR) chain. Exposed to animators, although rarely used.
		self.ik_ctr_chain = []
		for i, org_bone in enumerate(self.org_chain):
			fk_bone = org_bone.fk_bone
			ik_ctr_bone = self.new_bonei(self.spine_ik_secondary
				,name				= fk_bone.name.replace("FK", "IK-CTR")
				,source				= fk_bone
				,custom_shape 		= self.ensure_widget("Oval")
			)

			if i == 0:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_hips.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)
			if i == len(self.org_chain)-3:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_chest.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)

			if i >= len(self.org_chain)-2:
				# Last two spine controls should be parented to the chest control.
				ik_ctr_bone.parent = self.mstr_chest
			else:
				# The rest to the torso root.
				ik_ctr_bone.parent = self.limb_root_bone
			self.ik_ctr_chain.append(ik_ctr_bone)

		### Reverse IK (IK-R) chain. Damped track to IK-CTR of one lower index.
		next_parent = self.mstr_chest
		self.ik_r_chain = []
		for i, org_bone in enumerate(reversed(self.org_chain[1:])):	# We skip the first spine.
			fk_bone = org_bone.fk_bone
			ik_r_name = fk_bone.name.replace("FK", "IK-R")
			org_bone.ik_r_bone = ik_r_bone = self.new_bonei(self.spine_mch
				,name		 = ik_r_name
				,source 	 = fk_bone
				,head		 = fk_bone.head
				,tail 		 = fk_bone.prev.head
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			next_parent = ik_r_bone
			self.ik_r_chain.append(ik_r_bone)
			ik_r_bone.add_constraint('DAMPED_TRACK',
				subtarget = self.ik_ctr_chain[len(self.org_chain)-i-2].name
			)

		# IK chain
		next_parent = self.mstr_hips # First IK bone is parented to MSTR-Hips.
		self.ik_chain = []
		for i, org_bone in enumerate(self.org_chain):
			fk_bone = org_bone.fk_bone
			ik_name = fk_bone.name.replace("FK", "IK")
			ik_bone = self.new_bonei(self.spine_mch
				,name		 = ik_name
				,source		 = fk_bone
				,head		 = fk_bone.prev.head if i>0 else self.def_chain[0].head
				,tail		 = fk_bone.head if i>0 else self.fk_chain[0].head
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			self.ik_chain.append(ik_bone)
			next_parent = ik_bone

			damped_track_target = None
			head_tail = 1
			if i == len(self.org_chain)-1:
				# Special treatment for last IK bone...
				damped_track_target = self.ik_ctr_chain[-1].name
				head_tail = 0
				self.mstr_chest.custom_shape_transform = ik_bone
				if self.params.CR_spine_double:
					self.mstr_chest.parent.custom_shape_transform = ik_bone
			else:
				damped_track_target = self.ik_r_chain[-i-1].name

			if i > 0:
				# IK Stretch Copy Location
				con_name = "Copy Location (Stretchy Spine)"
				str_con = ik_bone.add_constraint('COPY_LOCATION'
					,space	   = 'WORLD'
					,name	   = con_name
					,subtarget = org_bone.ik_r_bone.name
					,head_tail = 1
				)

				# Influence driver
				influence_unit = 1 / (len(self.org_chain)-1)
				influence = influence_unit * i

				str_con.drivers.append({
					'prop' : 'influence',
					'expression' : f"var * {influence}",
					'variables' : [
						(self.properties_bone.name, self.ik_stretch_name)
					]
				})

				ik_bone.add_constraint('COPY_ROTATION'
					,space	   = 'WORLD'
					,subtarget = self.ik_ctr_chain[i-1].name
				)
				self.ik_ctr_chain[i-1].custom_shape_transform = ik_bone

			ik_bone.add_constraint('DAMPED_TRACK',
				subtarget = damped_track_target,
				head_tail = head_tail
			)

		# Attach FK to IK
		for i, ik_bone in enumerate(self.ik_chain[1:]):
			fk_bone = self.fk_chain[i]
			con_name = "Copy Transforms IK"
			ct_con = fk_bone.add_constraint('COPY_TRANSFORMS'
				,space	   = 'WORLD'
				,name	   = con_name
				,subtarget = ik_bone.name
			)

			ct_con.drivers.append({
				'prop' : 'influence',
				'variables' : [(self.properties_bone.name, self.ik_prop_name)]
			})

		# Store info for UI
		info = {
			"prop_bone"		: self.properties_bone,
			"prop_id" 		: self.ik_stretch_name,
		}
		self.add_ui_data("ik_stretches", self.category, self.spine_name, info, default=1.0)

		info = {
			"prop_bone"		: self.properties_bone,
			"prop_id"		: self.ik_prop_name,
		}
		self.add_ui_data("ik_switches", self.category, self.spine_name, info, default=0.0)

	def tweak_str_spine(self):
		# Tweak some display things
		for i, str_bone in enumerate(self.str_chain):
			if i == len(self.str_chain) - 1 - self.params.CR_chain_tip_control:
				str_bone.parent = self.fk_chain[-2]
			str_bone.custom_shape = self.ensure_widget('Cube_Flat')

	def attach_org_to_fk(self):
		"""Overrides."""

		# Parent ORG to FK. This is only important because STR- bones are owned by ORG- bones.
		# We want each FK bone to control the STR- bone of one higher index, eg. FK-Spine0 would control STR-Spine1.
		for i, org_bone in enumerate(self.org_chain):
			if i == 0:
				# First STR bone should by owned by the hips.
				org_bone.parent = self.mstr_hips
			elif i == len(self.org_chain)-1:
				org_bone.parent = self.fk_chain[-1]
			else:
				org_bone.parent = self.fk_chain[i-1]
		
		if self.params.CR_chain_tip_control:
			self.str_chain[-1].parent = self.fk_chain[-1]

	def register_parents(self):
		"""Register some primary controls as available parents for parent switching."""
		# Hips
		self.register_parent(self.mstr_hips, "Hips")
		# Final spine FK.
		self.register_parent(self.fk_chain[-1], "Chest")
		# Torso root.
		self.register_parent(self.limb_root_bone, "Torso")

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		super().define_bone_sets(params)
		"""Create parameters for this rig's bone sets."""
		cls.define_bone_set(params, "Spine Main Controls",	  preset=2,  default_layers=[cls.default_layers('IK_MAIN')]		)
		cls.define_bone_set(params, "Spine Parent Controls",  preset=8,  default_layers=[cls.default_layers('IK_MAIN')]		)
		cls.define_bone_set(params, "Spine IK Secondary",	  preset=10, default_layers=[cls.default_layers('IK_SECOND')]	)
		cls.define_bone_set(params, "Spine Mechanism",					 default_layers=[cls.default_layers('MCH')], 	  override='MCH')

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_spine_show_settings = BoolProperty(
			name		 = "Spine Settings"
			,description = "Reveal settings for the cloud_spine rig type"
		)
		params.CR_spine_offset_fk = BoolProperty(	# TODO: Implement this.
			name		 = "Offset FK Bones"
			,description = "FK Bones will be placed at the halfway points of original bones. Thanks to Bendy Bones, this can result in smoother deformation, but also some volume loss"
			,default	 = True
		)
		params.CR_spine_use_ik = BoolProperty(
			name		 = "Create IK Setup"
			,description = "If disabled, this spine rig will only have FK controls"
			,default	 = True
		)
		params.CR_spine_double = BoolProperty(
			name		 = "Double Controls"
			,description = "Make duplicates of the main spine controls"
			,default	 = True
		)

	@classmethod
	def draw_bone_set_params(cls, layout, params, set_info):
		if (set_info['name'] != "Spine IK Secondary" or params.CR_spine_use_ik) and \
			(set_info['name'] != "Spine Parent Controls" or params.CR_spine_double):
			super().draw_bone_set_params(layout, params, set_info)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_spine_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_spine_use_ik")
		cls.draw_prop(layout, params, "CR_spine_double")

		return layout

class Rig(CloudSpineRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)