from typing import List
from bpy.types import PropertyGroup
from ..rig_component_features.bone import BoneInfo

from bpy.props import BoolProperty
from mathutils import Vector

from .cloud_fk_chain import Component_Chain_FK

"""TODO
Re-implement FK-C bones (maybe under a param)
	Their values would probably have to be dependent on the length of the bone.
	Ie., longer bones slide more when rotated.
Bug: IK-CTR-Chest flies away when moving the chest master far, needs a DSP- bone?
"""

class Component_Spine_IKFK(Component_Chain_FK):
	"""Spine setup with FK, IK-like and stretchy IK controls."""
	ui_name = "Spine: IK/FK"
	forced_params = {
		'chain.segments' : 1
		,'fk_chain.double_first' : False
		,'fk_chain.hinge' : False
		,'fk_chain.display_center' : False
		,'fk_chain.root' : True
	}
	always_use_custom_props = True

	def initialize(self):
		"""Gather and validate data about the rig."""
		super().initialize()

		if self.params.spine.use_ik and not self.bone_count > 2:
			self.raise_metarig_error("Spine rig with IK must consist of a chain of at least 3 connected bones!")
		if not self.bone_count > 1:
			self.raise_metarig_error("Spine rig must consist of a chain of at least 2 connected bones!")

		self.spine_name = self.naming.slice_name(self.base_bone_name)[1]

		self.ik_prop_name = "ik_" + self.spine_name.lower()
		self.ik_stretch_name = "ik_stretch_" + self.spine_name.lower()

		self.root_torso = None

	def make_root_bone(self):
		"""Overrides cloud_fk_chain."""

		# Create Torso Master control
		limb_root_bone = self.bone_sets['Spine Main Controls'].new(
			name 		  = self.naming.make_name(["MSTR"], self.spine_name+"_Torso", [self.side_suffix])
			,parent		  = self.bones_org[0].parent
			,source 	  = self.bones_org[0]
			,head 		  = self.bones_org[0].center
			,custom_shape = self.ensure_widget("Torso_Master")
		)
		return limb_root_bone

	def make_fk_chain(self, org_chain) -> List[BoneInfo]:
		"""Overrides cloud_fk_chain."""
		fk_chain = super().make_fk_chain(org_chain)

		# Create master hip control
		self.mstr_hips = self.bone_sets['Spine Main Controls'].new(
				name					= self.naming.make_name(["MSTR"], self.spine_name+"_Hips", [self.side_suffix])
				,source					= org_chain[0]
				,head					= org_chain[0].center
				,custom_shape 			= self.ensure_widget("Hyperbola")
				,custom_shape_scale_xyz	= Vector((0.8, -0.8, 0.8))
				,parent					= self.root_bone
		)
		if self.params.spine.world_align:
			self.root_bone.flatten()
			self.mstr_hips.flatten()

		# Shift FK controls to their center.
		for fk_bone in self.bone_sets['FK Controls']:
			fk_bone.head = fk_bone.center
			if fk_bone.prev:
				fk_bone.prev.tail = fk_bone.head

		# Parent the first one to MSTR-Torso.
		self.bone_sets['FK Controls'][0].parent = self.root_bone

		return fk_chain

	def create_bone_infos(self, context):
		super().create_bone_infos(context)
		# If we want to parent things to the root bone, we use self.root_torso.
		# However, for spine.double to work, self.root_bone must be the bone
		# returned from create_parent_bone().
		self.root_torso = self.root_bone

		if self.params.spine.use_ik:
			self.make_ik_spine()
		self.tweak_str_spine()

		if self.params.spine.double:
			self.root_bone = self.create_parent_bone(self.root_torso, self.bone_sets['Spine Parent Controls'])

	def make_ik_spine(self):
		### Create master chest control
		chest_org = self.bones_org[-2]
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

		if self.params.spine.double:
			self.create_parent_bone(self.mstr_chest, self.bone_sets['Spine Parent Controls'])

		### IK Control (IK-CTR) chain. Exposed to animators, although rarely used.
		self.ik_ctr_chain = []
		for i, org_bone in enumerate(self.bones_org):
			fk_bone = org_bone.fk_bone
			ik_ctr_bone = self.bone_sets['Spine IK Secondary'].new(
				name				= fk_bone.name.replace("FK", "IK-CTR")
				,source				= fk_bone
				,custom_shape 		= self.ensure_widget('Circle')
				,custom_shape_scale_xyz = Vector((1, 1, 0.8))
			)

			if i == 0:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_hips.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)
			if i == len(self.bones_org)-3:
				ik_ctr_bone.add_constraint('COPY_ROTATION'
					,subtarget = self.mstr_chest.name
					,influence = 0.5
					,use_xyz   = [False, True, False]
				)

			if i >= len(self.bones_org)-2:
				# Last two spine controls should be parented to the chest control.
				ik_ctr_bone.parent = self.mstr_chest
			else:
				# The rest to the torso root.
				ik_ctr_bone.parent = self.root_torso
			self.ik_ctr_chain.append(ik_ctr_bone)

		### Reverse IK (IK-R) chain. Damped track to IK-CTR of one lower index.
		next_parent = self.mstr_chest
		self.ik_r_chain = []
		for i, org_bone in enumerate(reversed(self.bones_org[1:])):	# We skip the first spine.
			fk_bone = org_bone.fk_bone
			ik_r_name = fk_bone.name.replace("FK", "IK-R")
			org_bone.ik_r_bone = ik_r_bone = self.bone_sets['Spine Mechanism'].new(
				name		 = ik_r_name
				,source 	 = fk_bone
				,head		 = fk_bone.head
				,tail 		 = fk_bone.prev.head
				,parent		 = next_parent
			)
			next_parent = ik_r_bone
			self.ik_r_chain.append(ik_r_bone)
			ik_r_bone.add_constraint('DAMPED_TRACK',
				subtarget = self.ik_ctr_chain[len(self.bones_org)-i-2].name
			)

		# IK chain
		next_parent = self.mstr_hips # First IK bone is parented to MSTR-Hips.
		self.ik_chain = []
		for i, org_bone in enumerate(self.bones_org):
			fk_bone = org_bone.fk_bone
			ik_name = fk_bone.name.replace("FK", "IK")
			ik_bone = self.bone_sets['Spine Mechanism'].new(
				name		 = ik_name
				,source		 = fk_bone
				,head		 = fk_bone.prev.head if i>0 else self.bones_def[0].head
				,tail		 = fk_bone.head if i>0 else self.bone_sets['FK Controls'][0].head
				,parent		 = next_parent
			)
			self.ik_chain.append(ik_bone)
			next_parent = ik_bone

			damped_track_target = None
			head_tail = 1
			if i == len(self.bones_org)-1:
				# Special treatment for last IK bone...
				damped_track_target = self.ik_ctr_chain[-1].name
				head_tail = 0
				self.mstr_chest.custom_shape_transform = ik_bone
				if self.params.spine.double:
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
				influence_unit = 1 / (len(self.bones_org)-1)
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
		self.add_ui_data("IK", self.limb_name, info, label_name="IK Stretch", entry_name=self.spine_name, default=1.0)

		info = {
			"prop_bone"		: self.properties_bone,
			"prop_id"		: self.ik_prop_name,
		}
		self.add_ui_data("FK/IK Switch", self.limb_name, info, entry_name=self.spine_name, default=0.0)

	def tweak_str_spine(self):
		""" We need to parent the last non-tip STR control to the 2nd-to-last FK control,
		otherwise that FK control's rotation disconnects the spine from itself."""
		# TODO: Why isn't this parenting done in the same place where STR bones get parented normally?
		for i, str_bone in enumerate(self.main_str_bones):
			if i == len(self.main_str_bones) - 1 - self.params.chain.tip_control:
				str_bone.parent = self.bone_sets['FK Controls'][-2]

	def attach_org_to_fk(self, org_bones, fk_bones):
		"""Overrides cloud_fk_chain.
		Parent ORG to FK. This is important because STR- bones are owned by ORG- bones.
		We want each FK bone to control the STR- bone of one higher index,
		eg. FK-Spine0 would control STR-Spine1.
		"""
		fk_bones = self.bone_sets['FK Controls']	# TODO: Why does it error without this?
		for i, org_bone in enumerate(org_bones):
			if i == 0:
				# First STR bone should by owned by the hips.
				org_bone.parent = self.mstr_hips
			elif i == len(org_bones)-1:
				org_bone.parent = fk_bones[-1]
			else:
				org_bone.parent = fk_bones[i-1]

		if self.params.chain.tip_control:
			self.main_str_bones[-1].parent = fk_bones[-1]

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls):
		super().define_bone_sets()
		"""Create parameters for this rig's bone sets."""
		cls.define_bone_set('Spine Main Controls', color_palette='THEME03', collections=['IK Controls'])
		cls.define_bone_set('Spine Parent Controls', color_palette='THEME09', collections=['IK Controls'])
		cls.define_bone_set('Spine IK Secondary', color_palette='THEME11', collections=['IK Secondary'])
		cls.define_bone_set('Spine Mechanism', collections=['Mechanism Bones'], is_advanced=True)

	@classmethod
	def is_bone_set_used(cls, context, rig, params, set_name):
		if set_name == "spine_ik_secondary":
			return params.spine.use_ik
		if set_name == "spine_parent_controls":
			return params.spine.double

		return super().is_bone_set_used(context, rig, params, set_name)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)

		layout.separator()
		cls.draw_control_label(layout, "Spine")
		cls.draw_prop(context, layout, params.spine, 'use_ik')
		cls.draw_prop(context, layout, params.spine, 'double')
		cls.draw_prop(context, layout, params.spine, 'world_align')


class Params(PropertyGroup):
	use_ik: BoolProperty(
		name		 = "Create IK Spine"
		,description = "If disabled, this spine rig will only have FK controls"
		,default	 = True
	)
	double: BoolProperty(
		name		 = "Duplicate Controls"
		,description = "Make duplicates of the main spine controls"
		,default	 = True
	)
	world_align: BoolProperty(
		name		 = "World-Align Controls"
		,description = "Flatten the torso and hips to align with the closest world axis"
		,default	 = True
	)

class RigComponent(Component_Spine_IKFK):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)