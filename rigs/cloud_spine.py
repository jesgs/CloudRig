from bpy.props import BoolProperty
from mathutils import Vector

from .cloud_fk_chain import CloudFKChainRig
from .cloud_base import CloudBaseRig

"""TODO
Re-implement FK-C bones (maybe under a param)
	Their values would probably have to be dependent on the length of the bone. 
	Ie., longer bones slide more when rotated.
Bug: IK-CTR-Chest flies away when moving the chest master far, needs a DSP- bone?
Errors without an assert when it's just a single bone. Should be supported.
"""

class CloudSpineRig(CloudFKChainRig):
	"""Spine setup with FK, IK-like and stretchy IK controls."""

	forced_params = {
		'CR_chain_segments' : 1
		,'CR_fk_chain_double_first' : False
		,'CR_fk_chain_hinge' : False
		,'CR_fk_chain_display_center' : False
		,'CR_fk_chain_root' : True
	}
	always_use_custom_props = True

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		if self.params.CR_spine_use_ik:
			assert len(self.bones.org.main) > 2, "Spine with IK must consist of at least 3 connected bones."

		# UI Strings and Custom Property names
		self.category = self.naming.strip_org(self.base_bone)
		if self.params.CR_fk_chain_use_category_name:
			self.category = self.params.CR_fk_chain_category_name

		self.spine_name = "Spine"
		if self.params.CR_fk_chain_use_limb_name:
			self.spine_name = self.params.CR_fk_chain_limb_name.replace(" ", "_")

		self.ik_prop_name = "ik_" + self.spine_name.lower()
		self.ik_stretch_name = "ik_stretch_" + self.spine_name.lower()

		self.root_torso = None

	def make_root_bone(self):
		"""Overrides cloud_fk_chain."""

		# Create Torso Master control
		limb_root_bone = self.bone_sets['Spine Main Controls'].new(
			name 		  = self.naming.make_name(["MSTR"], self.spine_name+"_Torso", [self.side_suffix])
			,parent		  = self.bone_sets['Original Bones'][0].parent
			,source 	  = self.bone_sets['Original Bones'][0]
			,head 		  = self.bone_sets['Original Bones'][0].center
			,custom_shape = self.ensure_widget("Torso_Master")
		)
		return limb_root_bone

	def make_fk_chain(self):
		"""Overrides cloud_fk_chain."""
		super().make_fk_chain()

		# Create master hip control
		self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
				name					= self.naming.make_name(["MSTR"], self.spine_name+"_Hips", [self.side_suffix])
				,source					= self.bone_sets['Original Bones'][0]
				,head					= self.bone_sets['Original Bones'][0].center
				,custom_shape 			= self.ensure_widget("Hyperbola")
				,custom_shape_scale_xyz	= Vector((0.8, -0.8, 0.8))
				,parent					= self.root_bone
		)
		if self.params.CR_spine_world_align:
			self.root_bone.flatten()

		# Shift FK controls to their center.
		for fk_bone in self.bone_sets['FK Controls']:
			fk_bone.head = fk_bone.center
			if fk_bone.prev:
				fk_bone.prev.tail = fk_bone.head

		# Parent the first one to MSTR-Torso.
		self.bone_sets['FK Controls'][0].parent = self.root_bone

	def create_bone_infos(self):
		super().create_bone_infos()
		# If we want to parent things to the root bone, we use self.root_torso.
		# However, for CR_spine_double to work, self.root_bone must be the bone 
		# returned from create_parent_bone().
		self.root_torso = self.root_bone

		if self.params.CR_spine_use_ik:
			self.make_ik_spine()
		self.tweak_str_spine()

		if self.params.CR_spine_double:
			self.root_bone = self.create_parent_bone(self.root_torso, self.bone_sets['Spine Parent Controls'])

	def make_ik_spine(self):
		### Create master chest control
		chest_org = self.bone_sets['Original Bones'][-2]
		self.mstr_chest = self.bone_sets['Spine Main Controls'].new(
				name					  = f"MSTR-{self.spine_name}_Chest"
				,source 				  = chest_org
				,head					  = chest_org.center
				,tail 					  = chest_org.center + Vector((0, 0, self.scale))
				,custom_shape 			  = self.ensure_widget("Hyperbola")
				,custom_shape_scale_xyz   = Vector((0.8, -1.3, 0.8))
				,custom_shape_translation = Vector((0, chest_org.length*2, 0))
				,parent					  = self.root_torso
			)

		if self.params.CR_spine_double:
			double_mstr_chest = self.create_parent_bone(self.mstr_chest, self.bone_sets['Spine Parent Controls'])

		if self.params.CR_spine_world_align:
			self.mstr_hips.flatten()

		### IK Control (IK-CTR) chain. Exposed to animators, although rarely used.
		self.ik_ctr_chain = []
		for i, org_bone in enumerate(self.bone_sets['Original Bones']):
			fk_bone = org_bone.fk_bone
			ik_ctr_bone = self.bone_sets['Spine IK Secondary'].new(
				name				= fk_bone.name.replace("FK", "IK-CTR")
				,source				= fk_bone
				,custom_shape 		= self.ensure_widget('Circle')
				,custom_shape_scale_xyz = ((1, 1, 0.8))
			)

			if i == 0:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_hips.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)
			if i == len(self.bone_sets['Original Bones'])-3:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_chest.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)

			if i >= len(self.bone_sets['Original Bones'])-2:
				# Last two spine controls should be parented to the chest control.
				ik_ctr_bone.parent = self.mstr_chest
			else:
				# The rest to the torso root.
				ik_ctr_bone.parent = self.root_torso
			self.ik_ctr_chain.append(ik_ctr_bone)

		### Reverse IK (IK-R) chain. Damped track to IK-CTR of one lower index.
		next_parent = self.mstr_chest
		self.ik_r_chain = []
		for i, org_bone in enumerate(reversed(self.bone_sets['Original Bones'][1:])):	# We skip the first spine.
			fk_bone = org_bone.fk_bone
			ik_r_name = fk_bone.name.replace("FK", "IK-R")
			org_bone.ik_r_bone = ik_r_bone = self.bone_sets['Spine Mechanism'].new(
				name		 = ik_r_name
				,source 	 = fk_bone
				,head		 = fk_bone.head
				,tail 		 = fk_bone.prev.head
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			next_parent = ik_r_bone
			self.ik_r_chain.append(ik_r_bone)
			ik_r_bone.add_constraint('DAMPED_TRACK',
				subtarget = self.ik_ctr_chain[len(self.bone_sets['Original Bones'])-i-2].name
			)

		# IK chain
		next_parent = self.mstr_hips # First IK bone is parented to MSTR-Hips.
		self.ik_chain = []
		for i, org_bone in enumerate(self.bone_sets['Original Bones']):
			fk_bone = org_bone.fk_bone
			ik_name = fk_bone.name.replace("FK", "IK")
			ik_bone = self.bone_sets['Spine Mechanism'].new(
				name		 = ik_name
				,source		 = fk_bone
				,head		 = fk_bone.prev.head if i>0 else self.bone_sets['Deform Bones'][0].head
				,tail		 = fk_bone.head if i>0 else self.bone_sets['FK Controls'][0].head
				,parent		 = next_parent
				,hide_select = self.mch_disable_select
			)
			self.ik_chain.append(ik_bone)
			next_parent = ik_bone

			damped_track_target = None
			head_tail = 1
			if i == len(self.bone_sets['Original Bones'])-1:
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
				influence_unit = 1 / (len(self.bone_sets['Original Bones'])-1)
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
			fk_bone = self.bone_sets['FK Controls'][i]
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
		""" We need to parent the last non-tip STR control to the 2nd-to-last FK control,
		otherwise that FK control's rotation disconnects the spine from itself."""
		# TODO: Why isn't this parenting done in the same place where STR bones get parented normally?
		for i, str_bone in enumerate(self.bone_sets['Stretch Controls']):
			if i == len(self.bone_sets['Stretch Controls']) - 1 - self.params.CR_chain_tip_control:
				str_bone.parent = self.bone_sets['FK Controls'][-2]

	def attach_org_to_fk(self):
		"""Overrides cloud_fk_chain.
		Parent ORG to FK. This is important because STR- bones are owned by ORG- bones.
		We want each FK bone to control the STR- bone of one higher index, 
		eg. FK-Spine0 would control STR-Spine1.
		"""
		for i, org_bone in enumerate(self.bone_sets['Original Bones']):
			if i == 0:
				# First STR bone should by owned by the hips.
				org_bone.parent = self.mstr_hips
			elif i == len(self.bone_sets['Original Bones'])-1:
				org_bone.parent = self.bone_sets['FK Controls'][-1]
			else:
				org_bone.parent = self.bone_sets['FK Controls'][i-1]

		if self.params.CR_chain_tip_control:
			self.bone_sets['Stretch Controls'][-1].parent = self.bone_sets['FK Controls'][-1]

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		super().add_bone_set_parameters(params)
		"""Create parameters for this rig's bone sets."""
		cls.define_bone_set(params, 'Spine Main Controls',	  preset=2,  default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])
		cls.define_bone_set(params, 'Spine Parent Controls',  preset=8,  default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])
		cls.define_bone_set(params, 'Spine IK Secondary',	  preset=10, default_layers=[cls.DEFAULT_LAYERS.IK_SECOND])
		cls.define_bone_set(params, 'Spine Mechanism',					 default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)

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

		params.CR_spine_world_align = BoolProperty(
			name		 = "World-Align Controls"
			,description = "Flatten the torso and hips to align with the closest world axis"	# TODO: This makes sense to have for the torso, but flattening the hips only when IK is enabled seems pretty random.
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
	def is_bone_set_used(cls, params, set_info):
		if set_info['name'] == "Spine IK Secondary":
			return params.CR_spine_use_ik
		if set_info['name'] == "Spine Parent Controls":
			return params.CR_spine_double

		return super().is_bone_set_used(params, set_info)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_spine_show_settings"): return layout

		cls.draw_prop(layout, params, "CR_spine_use_ik")
		cls.draw_prop(layout, params, "CR_spine_double")
		cls.draw_prop(layout, params, "CR_spine_world_align")

		return layout

class Rig(CloudSpineRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)