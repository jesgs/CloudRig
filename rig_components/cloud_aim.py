from typing import Optional, List, Dict

import bpy
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, FloatProperty, StringProperty
from mathutils import Vector

from ..rig_component_features.bone import BoneInfo
from .cloud_base import Component_Base

from ..utils.maths import bounding_box_center

class Component_Aim(Component_Base):
	"""Create aim target controls for a single bone."""

	ui_name = "Aim"
	relinking_behaviour = "Constraints will be moved to the Eye Root Control."
	parent_switch_behaviour = "The active parent will own the Aim Target or the Group Master Target if there are multiple eye components with a matching string as their Eye Group paramter."
	parent_switch_overwrites_root_parent = False

	@property
	def bone_set_definitions(self):
		bone_set_definitions = super().bone_set_definitions
		bone_set_definitions.update({
			'aim_group_target_control' : {
				'preset' : 1,
				'default_layer' : Component_Base.DEFAULT_LAYERS.FACE_MAIN
			},
			'aim_target_controls' : {
				'preset' : 2,
				'default_layer' : Component_Base.DEFAULT_LAYERS.FACE_MAIN
			},
			'aim_root_control' : {
				'preset' : 2,
				'default_layer' : Component_Base.DEFAULT_LAYERS.FACE_SECOND
			},
			'aim_deform' : {
				'default_layer' : Component_Base.DEFAULT_LAYERS.DEF,
				'is_advanced' : True
			}
		})
		return bone_set_definitions

	def create_bone_infos(self):
		super().create_bone_infos()

		aim_org = self.bones_org[0]
		aim_bone = self.bone_sets.aim_group_target_control.new(
			name		 = self.bones_org[0].name.replace("ORG", "AIM")
			,source		 = aim_org
			,parent		 = aim_org
		)

		if self.params.aim.root:
			self.root_bone = self.make_root_bone(aim_org)

		self.group_master = None
		if self.params.aim.group != "":
			self.group_master = self.ensure_group_master()

		self.ctr_bone = self.make_aim_control(aim_org, aim_bone)
		self.target_bone = self.make_target_control(aim_bone, self.group_master)

		aim_bone.add_constraint('DAMPED_TRACK'
			,subtarget = self.target_bone.name
		)

		if self.params.aim.deform:
			def_bone = self.make_def_bone(self.ctr_bone, self.bone_sets.deform_bones)
			def_bone.parent = aim_org
			def_bone.add_constraint('COPY_TRANSFORMS', subtarget=self.ctr_bone.name)

		if self.params.aim.create_sub_control:
			self.create_eye_highlight(self.ctr_bone)

	def find_target_pos(self, bone: BoneInfo) -> Vector:
		"""Find location of where the target bone should be for an aim bone."""
		if self.params.aim.flatten:
			direction = bone.vector.normalized()
			# Ignore X axis
			direction[0] = 0.0
			return bone.head + direction * self.params.aim.target_distance * self.scale
		else:
			return bone.tail + bone.vector.normalized() * self.params.aim.target_distance * self.scale

	def make_target_control(self, bone: BoneInfo, parent: BoneInfo=None) -> BoneInfo:
		"""Set up target control for a bone."""
		if not parent:
			parent = bone.parent

		head = self.find_target_pos(bone)
		tail = head + bone.vector

		target_bone = self.bone_sets.aim_target_controls.new(
			name	= self.bones_org[0].name.replace("ORG", "TGT")
			,source = self.bones_org[0]
			,head	= head
			,tail	= tail
			,custom_shape = self.ensure_widget("Circle")
			,parent = parent
		)
		dsp_bone = self.create_dsp_bone(target_bone)
		dsp_bone.add_constraint('DAMPED_TRACK', subtarget=bone.name, track_axis='TRACK_NEGATIVE_Y')

		return target_bone

	def make_aim_control(self, org_bone, aim_bone) -> BoneInfo:
		"""Create direct control, with a display bone at the tip of it."""
		ctr_bone = self.bone_sets.aim_target_controls.new(
			name = self.naming.make_name(["CTR"], *self.naming.slice_name(org_bone.name)[1:])
			,source = org_bone
			,parent = org_bone.parent
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

	def make_root_bone(self, org_bone) -> BoneInfo:
		root_bone = self.bone_sets.aim_root_control.new(
			name = org_bone.name.replace("ORG", "ROOT")
			,source = org_bone
			,parent = org_bone.parent
			,custom_shape = self.ensure_widget('Square')
			,custom_shape_scale = 2
			,custom_shape_along_length = 1
		)

		org_bone.parent = root_bone

		return root_bone

	def create_eye_highlight(self, ctr_bone):
		name_slices = self.naming.slice_name(ctr_bone)
		name_slices[1] += "_Highlight"
		highlight_ctr = self.bone_sets.aim_target_controls.new(
			name = self.naming.make_name(*name_slices)
			,source = ctr_bone
			,parent = ctr_bone
			,custom_shape = self.ensure_widget("Circle")
			,custom_shape_scale = ctr_bone.custom_shape_scale/3
			,custom_shape_along_length = 1.05
		)

		prop_name = "follow_eye"
		info = {
			'prop_bone' : highlight_ctr,
			'prop_id' : prop_name,
		}
		self.add_ui_data("Face", "Eye Highlights", info, label_name="Eye Highlights Follow", entry_name=self.side_prefix+" Eye", default=1.0)
		arm_con = highlight_ctr.add_constraint('ARMATURE',
			targets = [
				{
					'subtarget' : ctr_bone.name
				},
				{
					'subtarget' : ctr_bone.parent.name
				}
			]
		)
		driver = {
			'prop' : 'targets[0].weight',
			'variables' : [
				(highlight_ctr.name, prop_name)
			]
		}
		arm_con.drivers.append(driver)
		driver = dict(driver)
		driver['prop'] = 'targets[1].weight'
		driver['expression'] = '1-var'
		arm_con.drivers.append(driver)

		self.lock_transforms(highlight_ctr, loc=[True, False, True], rot=False, scale=[False, True, False])
		self.make_def_bone(highlight_ctr, self.bone_sets.deform_bones)

	def relink(self):
		"""Override cloud_base.
		Move constraints from the ORG to the Eye Control bone and relink them.
		"""
		org = self.bones_org[0]
		if org == self.root_bone:
			org.relink()
			return
		for c in org.constraint_infos:
			self.root_bone.constraint_infos.append(c)
			org.constraint_infos.remove(c)
			for d in c.drivers:
				self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
			c.relink()

	def apply_parent_switching(self, parent_slots, *,
			child_bone=None, prop_bone=None, prop_name="",
			panel_name="Face", row_name="", label_name="", entry_name=""
		):
		"""Overrides cloud_base to apply the parent switching to the aim target
		or group master if it exists."""
		target_bone = self.group_master
		if not target_bone:
			target_bone = self.target_bone
		else:
			# Ensure parent switching for the group master
			if self.group_master.parent and self.group_master.parent.name == "P-"+self.group_master.name:
				# If the parent switching set-up already exists, don't create it again.
				return

		super().apply_parent_switching(parent_slots
			,child_bone = child_bone or target_bone
			,prop_bone = prop_bone or self.properties_bone
			,prop_name = prop_name
			,panel_name = panel_name
			,label_name = label_name or "Aim Target Parent"
			,row_name = row_name
			,entry_name = entry_name or self.params.aim.group + " Parent"
		)

	def find_aim_bones_in_group(self, group_name) -> List[bpy.types.PoseBone]:
		"""Return a list of all cloud_aim components with a matching Aim Group."""
		aim_bones = []
		for rig in self.generator.rig_list:
			if isinstance(rig, Component_Aim) and rig.group == group_name:
				aim_bone = self.obj.pose.bones[rig.base_bone]
				aim_bones.append(aim_bone)
		return aim_bones

	def ensure_group_master(self) -> Optional[BoneInfo]:
		"""This function will be called by each aim rig, but we want to make sure
		   it only runs once per aim group.
		"""

		# Check if a bone with the right name already exists and if it does, just return it.
		group_name = self.params.aim.group
		group_master_name = "MSTR-TGT-"+group_name
		existing = self.generator.find_bone_info(group_master_name)
		if existing:
			return existing

		aim_bones = self.find_aim_bones_in_group(group_name)

		# Find a parent to fall back to, although ideally the rigger specifies
		# parents using params.parenting.parent_switching.
		first_parent = ""
		for aim_bone in aim_bones:
			if aim_bone.parent and first_parent=="":
				first_parent = aim_bone.parent.name
				break

		if len(aim_bones) < 2:
			return None

		# Find center of all aim bones
		aims_center = bounding_box_center([b.head for b in aim_bones])

		# Find center of all targets
		target_positions = [self.find_target_pos(b) for b in aim_bones]
		target_center = bounding_box_center(target_positions)

		# Create a helper bone in the center.
		group_vec = target_center - aims_center
		center_bone = self.bone_sets.aim_group_target_control.new(
			name = "CEN-"+group_name
			,source = self.bones_org[0]
			,head = aims_center
			,tail = aims_center + group_vec.normalized() * self.scale
			,bbone_width = 0.1
			,parent = self.generator.find_bone_info(first_parent)
		)

		max_dist = 0
		for i, target_pos in enumerate(target_positions[1:]):
			prev = target_positions[i]
			dist = (target_pos - prev).length
			if dist > max_dist:
				max_dist = dist

		# Create the master bone.
		group_master = self.bone_sets.aim_group_target_control.new(
			name = group_master_name
			,source = self.bones_org[0]
			,head = target_center
			,tail = target_center + group_vec.normalized() * self.scale
			,custom_shape = self.ensure_widget('Circle')
			,use_custom_shape_bone_size = True
			,custom_shape_scale = (max_dist / self.scale) * 2
		)
		group_master.add_constraint('DAMPED_TRACK'
			,subtarget = center_bone.name
			,track_axis = 'TRACK_NEGATIVE_Y'
		)

		return group_master

	##############################
	# Parameters

	@classmethod
	def is_bone_set_used(cls, context, rig, params, set_name):
		if set_name == 'deform_bones':
			return params.aim.deform

		return super().is_bone_set_used(context, rig, params, set_name)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		cls.draw_prop(context, layout, params.aim, "group")
		cls.draw_prop(context, layout, params.aim, "target_distance")
		cls.draw_prop(context, layout, params.aim, "flatten")
		cls.draw_prop(context, layout, params.aim, "deform")
		cls.draw_prop(context, layout, params.aim, "root")
		cls.draw_prop(context, layout, params.aim, "create_sub_control")

class Params(PropertyGroup):
	group: StringProperty(
		name		 = "Aim Group"
		,default	 = "Eyes"
		,description = "Aim components belonging to the same Aim Group will have a shared master control generated for them"
	)

	target_distance: FloatProperty(
		name		 = "Target Distance"
		,default	 = 5.0
		,description = "Distance of the target from the aim bone. This value is not in blender units, but is a value relative to the scale of the rig"
		,min		 = 0
	)
	flatten: BoolProperty(
		name		 = "Flatten X"
		,description = "Discard the X component of the eye vector when placing the target control. Useful for eyes that have significant default rotation. This can result in the eye becoming cross-eyed in the default pose, but it prevents the eye targets from crossing each other or being too far from each other"
		,default	 = False
	)
	# TODO: Do this the same way as cloud_copy instead, ie. use the bone's use_deform property.
	deform: BoolProperty(
		name		 = "Create Deform"
		,default	 = False
		,description = "Create a deform bone for this rig"
	)
	# TODO: Move this to cloud_base.
	root: BoolProperty(
		name		 = "Create Root"
		,default	 = False
		,description = "Create a root bone for this rig"
	)
	create_sub_control: BoolProperty(
		name		 = "Create Sub-Control"
		,description = "Create a secondary control and deform bone attached to the aim control. Useful for eye highlights"
		,default	 = False
	)

class RigComponent(Component_Aim):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)