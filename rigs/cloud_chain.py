from typing import Tuple, List
from ..rig_features.bone import BoneInfo
from ..rig_features.bone_set import BoneSet

from bpy.props import BoolProperty, IntProperty
from copy import deepcopy

from .cloud_base import CloudBaseRig

class CloudChainRig(CloudBaseRig):
	"""Chain with cartoony squash and stretch controls."""
	relinking_behaviour = "Constraints will be moved to the STR bone at the metarig bone\'s head, or tail if the constraint name is prefixed with \"TAIL-\"."

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.is_cyclic = False
		self.chain_length = 0

		# Other rigs may want to access some bones, so we store them.
		self.main_str_bones: List[BoneInfo]
		self.str_chain: List[BoneInfo]
		self.tangent_helpers: List[BoneInfo]

	def create_bone_infos(self):
		super().create_bone_infos()
		# Determine if this is a cyclic chain rig (last bone touches first)
		self.is_cyclic = (self.bones_org[-1].tail - self.bones_org[0].head).length < 0.001 and not self.params.CR_chain_tip_control
		if self.is_cyclic:
			self.bones_org[0].prev = self.bones_org[-1]
			self.bones_org[-1].next = self.bones_org[0]

		# Calculate total and average bone length
		for org in self.bones_org:
			self.chain_length += org.length

		# Create Main STR controls
		self.main_str_bones = self.make_main_str_bones(self.bones_org)

		# Create Sub STR controls, in-between the Main ones.
		# They are organized into a list of (main, [sub1, sub2...]) tuples.
		str_sections = self.make_sub_str_sections(self.main_str_bones, self.bones_org)

		# Build a straight chain of STR bones that contains both main and sub
		# bones in order.
		self.str_chain = self.sort_str_sections_into_chain(str_sections, self.is_cyclic)

		self.tangent_helpers = []
		if self.params.CR_chain_bbone_density > 0:
			# Create tangent helpers that will control bendy bone curvature
			self.tangent_helpers = self.make_tangent_helpers(self.str_chain)

		self.make_def_chain(
			str_chain = self.str_chain
			,tangent_helpers = self.tangent_helpers
			,preserve_volume = self.params.CR_chain_preserve_volume
			,create_ctr_def_ctrls = self.params.CR_chain_unlock_deform
		)

		self.connect_parent_chain_rig()

	def sort_str_sections_into_chain(self
			,str_sections: List[Tuple[BoneInfo, List[BoneInfo]]]
			,is_cyclic: bool
		) -> List[BoneInfo]:
		"""Sort the main and sub STR bones into a chain, so each one knows
		which one comes before and after it."""
		str_chain = []
		for section in str_sections:
			str_chain.append(section[0])
			str_chain.extend(section[1])

		str_chain[0].prev = None
		prev = str_chain[0]
		for str_bone in str_chain[1:]:
			prev.next = str_bone
			str_bone.prev = prev
			str_bone.next = str_bone	# Only affects last STR.
			prev = str_bone

		if is_cyclic:
			str_chain[-1].next = str_chain[0]
			str_chain[0].prev = str_chain[-1]

		return str_chain

	def get_relink_target(self, org_i, con) -> BoneInfo:
		"""Return the bone to which a constraint should be moved to."""
		org_bone = self.bones_org[org_i]
		relink_bone = self.main_str_bones[org_i]
		if 'TAIL' in con.name:
			if len(self.main_str_bones) <= org_i + 1:
				# TODO: Add a log, don't totally cancel the generation!
				self.raise_error(f"Cannot move constraint {con.name} from {org_bone.name} to final STR bone since it doesn't exist! Make sure Final Control param is enabled!")
			relink_bone = self.main_str_bones[org_i + 1]

		if con.type == 'ARMATURE':
			relink_bone = self.create_parent_bone(relink_bone, self.bones_mch)
		return relink_bone

	def relink(self):
		"""Overrides cloud_base.

		Move constraints from ORG bones to main STR bones and relink them.

		If the constraint name contains 'TAIL', we move the constraint
		to the STR bone at the tip of the ORG bone rather than at the head.

		If the constraint type is Armature, create a parent helper bone to prevent
		the parenting from affecting the local matrix.
		"""
		for i, org in enumerate(self.bones_org):
			for c in org.constraint_infos[:]:
				to_bone = self.get_relink_target(i, c)
				if not to_bone:
					continue

				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	def make_main_str_bones(self, org_chain: BoneSet) -> List[BoneInfo]:
		"""Create the main stretch controls:
		One for each ORG bone, plus optionally one more at the end of the chain."""
		main_str_bones = []
		if self.params.CR_chain_tip_control:
			# Temporarily create an extra ORG BoneInfo.
			last_org = org_chain[-1]
			extra_org = org_chain.new(
				name = last_org.name.replace("ORG", "ORG-TIP")
				,source = last_org
				,parent = last_org
			)
			extra_org.put(last_org.tail)
			if self.is_cyclic:
				self.org_chain[0].prev = extra_org

		for i, org_bone in enumerate(org_chain):
			main_str_bone = self.make_main_str_bone(org_bone, i)
			main_str_bones.append(main_str_bone)

		if self.params.CR_chain_tip_control:
			extra_org = org_chain[-1]
			org_chain.remove(extra_org)
			del extra_org

		return main_str_bones

	def make_main_str_bone(self
			,org_bone: BoneInfo
			,org_i: int
		) -> BoneInfo:
		"""Create and return a main STR control."""
		segments = self.params.CR_chain_segments
		direction = org_bone.vector
		if org_bone.prev:
			# Rotate the bone halfway towards the previous one TODO: This shouldn't happen for the last STR bone?
			direction = org_bone.tail - org_bone.prev.head
		if org_i == 0 and self.is_cyclic:
			direction = (org_bone.tail - self.bones_org[-1].head).normalized()

		str_name = org_bone.name.replace("ORG", "STR")
		sliced = self.naming.slice_name(str_name)

		# Add a 1 at the end unless there's only 1 segment.
		num_segments = self.get_num_segments_of_section(org_bone)
		if num_segments > 1:
			sliced[1] += "1"
		str_name = self.naming.make_name(*sliced)
		main_str = self.bone_sets['Stretch Controls'].new(
			name = str_name
			,source = org_bone
			,vector = direction
			,length = org_bone.length / segments / 2
			,custom_shape_scale = -0.6
			,parent = org_bone
			,inherit_scale = 'AVERAGE'
		)

		if not self.is_cyclic and org_i == 0:
			main_str.custom_shape = self.ensure_widget('Sphere_Half')
		else:
			main_str.custom_shape = self.ensure_widget("Sphere")

		# Create alignment helpers, to make sure the bendy bones don't flip out
		# when the chain has a zig-zaggy shape, and the STR-H bones try to copy
		# rotations from the STR bones.
		# TODO: There should be a better solution here, at least code-wise if not rig-wise.
		main_str.align_in = main_str
		main_str.align_out = main_str
		if self.params.CR_chain_segments > 1 and \
				org_bone.prev and self.params.CR_chain_align_roll:
			main_str.roll_type = 'ACTIVE'		# TODO: Setting bone rolls like this is expensive because we rely on bpy.ops.
			main_str.roll_bone = org_bone.name
			main_str.roll = 0
			main_str.align_in = self.bone_sets['Mechanism Bones'].new(
				name = str_name.replace("STR", "STR-RI")
				,source = org_bone.prev
				,parent = main_str
				,head = main_str.head
				,tail = main_str.head + org_bone.prev.vector * main_str.length
			)
			main_str.align_out = self.bone_sets['Mechanism Bones'].new(
				name = str_name.replace("STR", "STR-RO")
				,source = org_bone
				,parent = main_str
				,head = main_str.head
				,tail = main_str.head + org_bone.vector * main_str.length
			)

		return main_str

	def make_sub_str_sections(self
			,main_str_bones: List[BoneInfo]
			,org_chain: BoneSet
		) -> List[Tuple[BoneInfo, List[BoneInfo]]]:
		"""Create sub-STR controls inbetween the main ones.
		Return a list of (main STR, [sub STRs]) tuples.
		"""

		# Storage for sections of sub-STR bones. This is a list of tuples where
		# the first element is a main STR bone, and the 2nd element is a list of its sub-STR bones.
		sections = [[main_str, []] for main_str in main_str_bones]

		num_sections = len(main_str_bones)-1
		if self.is_cyclic:
			num_sections += 1

		for idx in range(num_sections):
			org_bone = org_chain[idx]
			main_start = main_str_bones[idx]

			end_idx = idx + 1
			if idx == len(main_str_bones)-1 and self.is_cyclic:
				# The end STR of the last section of a cyclic chain is the first STR.
				end_idx = 0
			main_end = main_str_bones[end_idx]

			section = self.make_sub_str_section(org_bone, main_start, main_end)
			sections[idx][1] = section
			main_start.sub_bones = section

		return sections

	def get_num_segments_of_section(self, org_bone: BoneInfo) -> int:
		"""Child classes may want to override this."""
		if org_bone == self.bones_org[-1] and not self.params.CR_chain_tip_control:
			return 1
		return self.params.CR_chain_segments

	def make_sub_str_section(self
			,org_bone: BoneInfo
			,main_start: BoneInfo
			,main_end: BoneInfo
		) -> List[BoneInfo]:
		"""Create sub-STR controls using two others as anchor points."""

		num_segments = self.get_num_segments_of_section(org_bone)

		section = []
		for idx in range(num_segments-1):
			section.append(self.make_sub_str_bone(org_bone, main_start, main_end, num_segments, idx+1))
		return section

	def make_sub_str_bone(self
			,org_bone: BoneInfo
			,main_start: BoneInfo
			,main_end: BoneInfo
			,num_segments: int
			,index: int
		) -> BoneInfo:
		# Add the index after the base name
		sliced = self.naming.slice_name(main_start.name)
		base_name = sliced[1][:-1] + str(index+1)
		sub_str_name = self.naming.make_name(sliced[0], base_name, sliced[2])

		vector = main_end.head - main_start.head
		unit = vector / num_segments

		sub_str = self.bone_sets['Stretch Controls'].new(
			name = sub_str_name
			,source = org_bone
			,parent = org_bone
			,head = main_start.head + (unit * index)
			,length = vector.length / num_segments / 2
			,custom_shape = self.ensure_widget("Sphere")
			,custom_shape_scale = -0.4
			,inherit_scale = 'AVERAGE'
		)
		sub_str.parent = self.make_sub_str_helper(
			sub_str, main_start, main_end, num_segments, index
		)

		# TODO: Remove these useless refs
		sub_str.align_in = sub_str
		sub_str.align_out = sub_str

		return sub_str

	def make_sub_str_helper(self
			,sub_str: BoneInfo
			,main_start: BoneInfo
			,main_end: BoneInfo
			,num_segments: int
			,index: int
		) -> BoneInfo:
		"""Create STR-H bones that keep STR controls between two main STR controls."""
		str_h_bone = self.bone_sets['Stretch Helpers'].new(
			name 		 = self.naming.add_prefix(sub_str.name, "H")
			,source 	 = sub_str
			,bbone_width = sub_str.bbone_width
			,parent		 = sub_str.parent
		)
		sub_str.parent = str_h_bone

		influence_unit = 1 / num_segments
		influence = index * influence_unit
		str_h_bone.add_constraint('COPY_LOCATION'
			,space		= 'WORLD'
			,subtarget	= main_start
		)
		str_h_bone.add_constraint('COPY_LOCATION'
			,space		= 'WORLD'
			,subtarget	= main_end
			,influence	= influence
		)
		str_h_bone.add_constraint('COPY_ROTATION'
			,space		= 'WORLD'
			,subtarget	= main_start.align_out
		)
		str_h_bone.add_constraint('COPY_ROTATION'
			,space		= 'WORLD'
			,subtarget	= main_end.align_in
			,influence	= influence
		)
		str_h_bone.add_constraint('DAMPED_TRACK', subtarget=main_end)

		return str_h_bone

	def make_tangent_helpers(self, str_chain: List[BoneInfo]) -> List[BoneInfo]:
		"""Create tangent helpers for each STR bone."""
		tangent_helpers = []

		for i, str_bone in enumerate(str_chain):
			str_bone.tangent_helper = self.make_tangent_helper(		# TODO: remove satanic reference if at all possible (probably won't be possible in cloud_face_chain though)
				str_bone = str_bone
				,prev_str = str_bone.prev or str_bone
				,next_str = str_bone.next or str_bone
				,smooth = self.params.CR_chain_smooth_spline
			)
			tangent_helpers.append(str_bone.tangent_helper)

		return tangent_helpers

	def make_tangent_helper(self
			,str_bone: BoneInfo
			,prev_str: BoneInfo = None
			,next_str: BoneInfo = None
			,smooth = False,
		) -> BoneInfo:
		"""Create a child bone for an STR bone with Damped Track constraints
		to aim at the previous and next STR bones."""
		handle_bone = self.bone_sets['Stretch Helpers'].new(
			name = self.naming.add_prefix(str_bone, "TAN")
			,source = str_bone
			,parent = str_bone
			,inherit_scale = 'NONE'
		)

		if smooth:
			assert prev_str and next_str, "Previous and next STR can only be None if smooth=False. Otherwise, pass str_bone."
			handle_bone.add_constraint('DAMPED_TRACK'
				,name		= "Damped Track Next"
				,subtarget	= next_str.name
				,track_axis	= 'TRACK_Y'
			)
			handle_bone.add_constraint('COPY_LOCATION', index=0
				,name = "Copy Location Prev"
				,subtarget = prev_str.name
				,space = 'WORLD'
			)

			# For main STR bones the parent is the ORG bone,
			# for sub STR bones it's the STR-H bone.
			handle_bone.parent = str_bone.parent
			handle_bone.add_constraint('COPY_TRANSFORMS'
				,name = "Copy STR Transforms"
				,subtarget = str_bone.name
				,target_space = 'LOCAL_OWNER_ORIENT'
			)

		if self.params.CR_chain_preserve_volume:
			handle_bone.inherit_scale = 'ALIGNED'
		else:
			handle_bone.add_constraint('COPY_SCALE'
				,subtarget = str_bone.name
				,space = 'WORLD'
			)

		return handle_bone

	def make_def_chain(self
			,str_chain: List[BoneInfo]
			,tangent_helpers: List[BoneInfo]
			,preserve_volume: bool
			,create_ctr_def_ctrls: bool
		) -> List[BoneInfo]:
		"""Create a deform chain stretching from one STR bone to the next.
		"""

		assert len(tangent_helpers) in [0, len(str_chain)], "tangent_helpers should be either empty or equal length as str_chain, depending on Smooth Spline param."

		# For each STR control, create a deform bone between it and the next one.
		for i, str_bone in enumerate(str_chain):
			if i == len(str_chain) - 1 and self.params.CR_chain_tip_control:
				# Don't create the last one when it's the tip control.
				continue

			if not str_bone.next:
				# This happens when tip_control=False.
				tail = str_bone.source.tail
			else:
				tail = str_bone.next.head
			org_bone = str_bone.source

			def_name = str_bone.name.replace("STR", "DEF")
			def_bone = self.bones_def.new(
				name		= def_name
				,source		= org_bone
				,parent		= str_bone
				,head		= str_bone.head
				,tail		= tail
				,use_deform	= True
			)

			if i == len(str_chain) - 1 and not self.is_cyclic:
				# Don't set up the last one unless we're a cyclic rig, since it has no next STR.
				def_bone.tail = org_bone.tail
				def_bone.inherit_scale = 'ALIGNED'		# TODO: In FK chain rigs, this last lonely deform bone should be parented to FK for good scaling behaviour.
				continue

			if create_ctr_def_ctrls:
				self.make_def_control(str_bone, def_bone)

			self.setup_deform_bone(
				def_bone = def_bone
				,org_bone = org_bone
				,str_bone = str_bone
				,next_str_bone = str_bone.next
				,preserve_volume = preserve_volume
			)

		return self.bones_def

	def setup_deform_bone(self
			,def_bone: BoneInfo
			,org_bone: BoneInfo
			,str_bone: BoneInfo
			,next_str_bone: BoneInfo
			,preserve_volume: bool
		):
		"""Configure BBone setup for def_bone."""

		# Stretch to next STR bone.
		if not self.params.CR_chain_unlock_deform:
			def_bone.add_constraint('STRETCH_TO'
				,subtarget = next_str_bone
				,use_bulge_min = not preserve_volume
				,use_bulge_max = not preserve_volume
			)

		# Set BBone Segments according to BBone Density param.
		def_bone.bbone_segments = self.determine_num_bbone_segments(org_bone, def_bone)
		# If bbone_density is >0, force at least 2 bbone_segments.
		# Otherwise it's not a bendy bone.
		if self.params.CR_chain_bbone_density > 0 and def_bone.bbone_segments < 2:
			def_bone.bbone_segments = 2
		elif self.params.CR_chain_bbone_density == 0:
			# If we don't have bendy bones then we're done.
			return

		# Set initial ease according to Sharp Sections param.
		if self.params.CR_chain_sharp:
			if str_bone in self.main_str_bones:
				def_bone.bbone_easein = 0
			if str_bone.next in self.main_str_bones:
				def_bone.bbone_easeout = 0

		def_bone.bbone_handle_type_start	  = 'TANGENT'
		def_bone.bbone_handle_type_end		  = 'TANGENT'
		def_bone.bbone_custom_handle_start	  = str_bone.tangent_helper
		def_bone.bbone_handle_use_scale_start = [True, False, True]
		def_bone.bbone_handle_use_scale_end	  = [True, False, True]
		if hasattr(next_str_bone, 'tangent_helper'):
			# This can be False when connecting to a parent chain rig that has Smooth Spline=False.
			def_bone.bbone_custom_handle_end = next_str_bone.tangent_helper

		# B-Bone ease drivers
		if not preserve_volume:
			def_bone.inherit_scale = 'NONE'
		self.make_bbone_ease_drivers(def_bone)

		if self.params.CR_chain_shape_key_helpers and def_bone.prev:
			self.make_shape_key_helper(def_bone.prev, def_bone)

	def determine_num_bbone_segments(self
			,org_bone: BoneInfo
			,def_bone: BoneInfo
		) -> int:
		"""Determine how many deform and b-bone segments should be in a section of the chain."""
		average_bone_length = self.chain_length / len(self.bones_org)	# TODO: This might be wrong now because we add a bone to bones_org when tip control is enabled...
		bbone_density = round(org_bone.length/average_bone_length *
			self.params.CR_chain_bbone_density * self.params.CR_chain_segments)

		bbone_segments = int( bbone_density / (org_bone.length / def_bone.length) )
		if self.params.CR_chain_bbone_density > 0:
			# Force at least 2 bbone_segments, otherwise it's not a bendy bone.
			bbone_segments = max(bbone_segments, 2)

		return bbone_segments

	def make_bbone_ease_drivers(self, def_bone: BoneInfo):
		### Ease In/Out
		easein_var = {
			'type' : 'TRANSFORMS',
			'targets' : [{
				'bone_target' : def_bone.bbone_custom_handle_start.name,
				'transform_type' : 'SCALE_Y',
				'transform_space' : 'LOCAL_SPACE',
			}]
		}
		easein_driver = {
			'expression' : "(YScale-AvgScale)",
			'prop' : "bbone_easein",
			'variables' : {
				'YScale' : easein_var,
				'AvgScale' : {
					'type' : 'TRANSFORMS',
					'targets' : [{
						'bone_target' : def_bone.bbone_custom_handle_start.name,
						'transform_space' : 'LOCAL_SPACE',
						'transform_type' : 'SCALE_AVG',
					}]
				}
			}
		}

		# Ease In
		if def_bone.bbone_handle_type_start == 'TANGENT':
			def_bone.drivers.append(easein_driver)

		# Ease Out
		if def_bone.bbone_handle_type_end == 'TANGENT' and \
				def_bone.bbone_custom_handle_end:
			easeout_driver = deepcopy(easein_driver)
			easeout_driver['prop'] = "bbone_easeout"
			easeout_driver['variables']['YScale']['targets'][0]['bone_target'] = def_bone.bbone_custom_handle_end.name
			easeout_driver['variables']['AvgScale']['targets'][0]['bone_target'] = def_bone.bbone_custom_handle_end.name
			def_bone.drivers.append(easeout_driver)

	def make_def_control(self
			,str_bone: BoneInfo
			,def_bone: BoneInfo
		) -> BoneInfo:
		"""Create CTR-DEF controls that can be used to nudge deform bones
		completely independently from their neighbours.
		"""
		def_bone_control = self.create_parent_bone(def_bone, bone_set=self.bone_sets['Deform Controls'])
		def_bone_control.name = def_bone_control.name.replace("DEF-P-", "CTR-DEF-")
		def_bone_control.inherit_scale = 'ALIGNED'
		def_bone.add_constraint('COPY_SCALE'
			,subtarget = def_bone_control.name
			,space = 'WORLD'
			,use_xyz = [False, True, False]
		)
		def_bone_parent = self.create_parent_bone(def_bone_control, bone_set=self.bone_sets['Deform Helpers'])
		def_bone_parent.parent = str_bone.parent
		def_bone_parent.add_constraint('COPY_LOCATION', subtarget=str_bone.name, space='WORLD')
		def_bone_control.head = def_bone_control.center
		def_bone_control.custom_shape_scale_xyz *= 0.7

		if str_bone.next:
			def_bone_parent.add_constraint('STRETCH_TO'
				,subtarget = str_bone.next.name
				,use_bulge_min = not self.params.CR_chain_preserve_volume
				,use_bulge_max = not self.params.CR_chain_preserve_volume
			)
		def_bone_control.custom_shape = self.ensure_widget('Cube')
		def_bone_control.custom_shape_scale_xyz.y = 0.1
		def_bone_control.layers = self.bone_sets['Deform Controls'].layers[:] # TODO: This should not be necessary!

		# Add drivers to BBone Roll so that rotating CTR-DEF controls on
		# local Y axis gives the results an animator might expect.
		for rna_prop in ['bbone_rollin', 'bbone_rollout']:
			roll_driver = {
				'prop' : rna_prop,
				'variables' : {
					'var' : {
						'type' : 'TRANSFORMS',
						'targets' : [{
							'bone_target' : def_bone_control.name,
							'transform_space' : 'LOCAL_SPACE',
							'rotation_mode' : 'SWING_TWIST_Y',
							'transform_type' : 'ROT_Y',
						}]
					}
				}
			}
			def_bone.drivers.append(roll_driver)

		# Add drivers to BBone Scale so that scaling CTR-DEF controls works
		for i, transform in [(0, 'SCALE_X'), (2, 'SCALE_Z')]:
			for rna_prop in ['bbone_scalein', 'bbone_scaleout']:
				def_bone.drivers.append({
						'prop' : rna_prop,
						'index' : i,
						'variables' : {
							'var' : {
								'type' : 'TRANSFORMS',
								'targets' : [{
									'bone_target' : def_bone_control.name,
									'transform_type' : transform,
									'transform_space' : 'LOCAL_SPACE'
								}]
							}
						}
					}
				)

		return def_bone_control

	def make_shape_key_helper(self
			,def_bone_1: BoneInfo
			,def_bone_2: BoneInfo
		) -> BoneInfo:
		"""
		Create SKP and SKH helper bones.

		Reading the local rotation of SKH
		gives us the rotation that we can use to activate corrective
		shape keys. It will be the rotational difference between the
		end of def_bone_1 and the start of def_bone_2.
		"""

		# SKP (Shape Key Helper Parent): Copy Transforms of the b-bone tail
		# of def_bone_1.
		skp_bone = self.bone_sets['Shape Key Helpers'].new(
			name		 = def_bone_1.name.replace("DEF", "SKP")
			,source		 = def_bone_1
			,head		 = def_bone_1.tail.copy()
			,tail		 = def_bone_1.tail + def_bone_1.vector
			,parent		 = def_bone_1
		)
		skp_bone.scale_length(0.3)
		skp_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_1.name
			,use_bbone_shape = True
			,head_tail		 = 1
		)

		# SKH (Shape Key Helper): This is parented to SKP and Copy Transforms
		# of the b-bone head of def_bone_2.
		skh_bone = self.bone_sets['Shape Key Helpers'].new(
			name		 = def_bone_1.name.replace("DEF", "SKH")
			,source		 = def_bone_1
			,head		 = def_bone_2.head.copy()
			,tail		 = def_bone_2.tail.copy()
			,parent		 = skp_bone
		)
		skh_bone.scale_width(2)
		skh_bone.scale_length(0.4)
		skh_bone.add_constraint('COPY_TRANSFORMS'
			,space			 = 'WORLD'
			,subtarget		 = def_bone_2.name
			,use_bbone_shape = True
			,head_tail		 = 0
		)
		return skh_bone

	def connect_parent_chain_rig(self):
		"""Connect two separate but connected cloud_chain rigs.

		If the parent rig is a connected chain rig with tip_control=False,
		make the last DEF bone of that rig stretch to this rig's first STR.
		"""

		# Check if we can connect into the parent rig
		parent_rig = self.rigify_parent
		if not isinstance(parent_rig, CloudChainRig): return
		if parent_rig.params.CR_chain_tip_control: return
		meta_org_bone = self.meta_bone(self.naming.strip_org(self.bones_org[0]))
		if not meta_org_bone.bone.use_connect: return

		parent_rig.params.CR_chain_tip_control = True
		last_def = parent_rig.bones_def[-1]
		last_str = parent_rig.str_chain[-1]
		last_org = parent_rig.bones_org[-1]
		parent_rig.setup_deform_bone(
			def_bone = last_def
			,org_bone = last_org
			,str_bone = last_str
			,next_str_bone = self.str_chain[0]
			,preserve_volume = parent_rig.params.CR_chain_preserve_volume
		)
		last_str.next = self.str_chain[0]
		last_str.custom_shape = self.str_chain[0].custom_shape = self.ensure_widget('Sphere')
		if self.params.CR_chain_shape_key_helpers or parent_rig.params.CR_chain_shape_key_helpers:
			self.make_shape_key_helper(last_def, self.bones_def[0])
		if self.params.CR_chain_smooth_spline:
			self.tangent_helpers[0].constraint_infos[0].subtarget = parent_rig.str_chain[-1]
		if parent_rig.params.CR_chain_smooth_spline:
			parent_rig.tangent_helpers[-1].constraint_infos[1].subtarget = self.str_chain[0]
		if parent_rig.params.CR_chain_unlock_deform:
			parent_rig.make_def_control(last_str, last_def)

	##############################
	# Parameters

	@classmethod
	def is_bone_set_used(cls, params, set_info):
		# We only want to draw this bone set UI if the option for it is enabled.
		if set_info['name'] in ["Deform Controls", "Deform Helpers"]:
			return params.CR_chain_unlock_deform
		return super().is_bone_set_used(params, set_info)

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Stretch Controls', preset=8,	default_layers=[cls.DEFAULT_LAYERS.STRETCH])
		cls.define_bone_set(params, 'Deform Controls', preset=5,	default_layers=[cls.DEFAULT_LAYERS.DEF_CTR])
		cls.define_bone_set(params, 'Deform Helpers', 				default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)
		cls.define_bone_set(params, 'Stretch Helpers',				default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)
		cls.define_bone_set(params, 'Shape Key Helpers',			default_layers=[cls.DEFAULT_LAYERS.MCH], is_advanced=True)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_chain_segments = IntProperty(	# TODO: It would be more intuitive to rename this to "Sub-Controls" and set default to 0, change code logic accordingly, and do metarig versioning.
			 name		 = "Stretch Segments"
			,description = "Number of bendy bones to create for each original bone"
			,default	 = 1
			,min		 = 1
			,max		 = 9
		)
		params.CR_chain_bbone_density = IntProperty(
			 name		 = "B-Bone Density"
			,description = "Average number of B-Bone Segments per deform bone. Longer bones will have more, shorter ones fewer, to get an even distribution. There will be a minimum of 2 B-Bone Segments unless this parameter is 0"
			,default	 = 10
			,min		 = 0
			,max		 = 32
		)
		params.CR_chain_unlock_deform = BoolProperty(
			 name		 = "Create Deform Controls"
			,description = "Create CTR-DEF controls that allow Deform bones to be controlled directly"
			,default	 = False
		)
		params.CR_chain_shape_key_helpers = BoolProperty(
			 name		 = "Create Shape Key Helpers"
			,description = "Create SKH bones that read the rotation between two deform bones, which can be used to drive corrective shape keys"
		)
		params.CR_chain_sharp = BoolProperty(
			 name		 = "Sharp Sections"
			,description = "B-Bone EaseIn/Out is set to 0 for bones connecting two sections"
			,default	 = False
		)
		params.CR_chain_smooth_spline = BoolProperty(
			 name		 = "Smooth Spline"
			,description = "B-Bone Splines affect their neighbours for smoother curves"
			,default	 = False
		)

		# This parameter is not exposed, and only exists for backwards compatibility currently.
		params.CR_chain_align_roll = BoolProperty(
			 name		 = "Align Roll"
			,description = "Re-calculate the bone roll of STR controls based on the ORG bones"
			,default	 = True
		)
		params.CR_chain_tip_control = BoolProperty(
			 name		 = "Tip Control"
			,description = "Add the final control at the end of the chain. Disabling this allows you to connect another chain to this one, or to make this chain loop into itself"
			,default	 = True
		)
		params.CR_chain_preserve_volume = BoolProperty(
			 name		 = "Preserve Volume"
			,description = "Squash and stretch will preserve volume"
			,default	 = False
		)

	@classmethod
	def draw_bendy_params(cls, layout, context, params):
		cls.draw_prop(layout, params, 'CR_chain_bbone_density')
		sharp = cls.draw_prop(layout, params, 'CR_chain_sharp')
		smooth = cls.draw_prop(layout, params, 'CR_chain_smooth_spline')
		sharp.enabled = smooth.enabled = params.CR_chain_bbone_density > 0

		if cls.is_advanced_mode(context):
			cls.draw_prop(layout, params, 'CR_chain_preserve_volume')
			cls.draw_prop(layout, params, 'CR_chain_shape_key_helpers')
			cls.draw_prop(layout, params, 'CR_chain_unlock_deform')

	@classmethod
	def draw_control_params(cls, layout, context, params):
		cls.draw_control_label(layout, "Stretch")
		cls.draw_prop(layout, params, 'CR_chain_segments')
		cls.draw_prop(layout, params, 'CR_chain_tip_control')

class Rig(CloudChainRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)