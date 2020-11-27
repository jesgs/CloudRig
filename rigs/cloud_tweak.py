from bpy.props import BoolProperty
from .cloud_base import CloudBaseRig
from ..bone import BoneInfo, BoneSet
from .cloud_copy import bendy_parenting, add_parent_param, draw_parent_param

class CloudTweakRig(CloudBaseRig):
	"""Tweak a single bone with the same name as this bone in the generated rig."""

	def initialize(self):
		super().initialize()

		self.orgless_name = self.base_bone.replace("ORG-", "")

	def prepare_bones(self):
		super().prepare_bones()
		tweak_bone = self.generator.find_bone_info(self.orgless_name)
		meta_bone = self.meta_bone(self.orgless_name)
		org_bi = self.org_chain[0]

		if not tweak_bone:
			self.add_log("No bone to tweak", trouble_bone=self.orgless_name, description=f"Could not find a bone called {self.orgless_name} on the generated rig. If it exists, make sure the cloud_tweak bone is lower in the hierarchy than the target bone's rig.")
			return

		if self.params.CR_tweak_transforms:
			tweak_bone.head = org_bi.head.copy()
			tweak_bone.tail = org_bi.tail.copy()
			tweak_bone.roll = org_bi.roll
			tweak_bone.bbone_x = org_bi.bbone_x
			tweak_bone.bbone_z = org_bi.bbone_z

		# Transfer and relink constraints and their drivers
		if not self.params.CR_tweak_constraints_additive:
			tweak_bone.clear_constraints()
		for c in org_bi.constraint_infos:
			tweak_bone.constraint_infos.append(c)
			c.relink()
			# Relink constraint drivers
			for d in c.drivers:
				self.relink_driver(d)
			org_bi.constraint_infos.remove(c)
			for d in c.drivers:
				self.obj.driver_remove(f'pose.bones["{org_bi.name}"].constraints["{c.name}"].{d["prop"]}')

		# Transfer and relink bone drivers
		for d in org_bi.drivers[:]:
			tweak_bone.drivers.append(d)
			org_bi.drivers.remove(d)
			self.relink_driver(d)

		if self.params.CR_tweak_locks:
			tweak_bone.lock_location = org_bi.lock_location[:]
			tweak_bone.lock_rotation = org_bi.lock_rotation[:]
			tweak_bone.lock_rotation_w = org_bi.lock_rotation_w
			tweak_bone.lock_scale = org_bi.lock_scale[:]

		if self.params.CR_tweak_rot_mode:
			tweak_bone.rotation_mode = org_bi.rotation_mode

		if self.params.CR_tweak_shape:
			tweak_bone.custom_shape = org_bi.custom_shape
			tweak_bone.custom_shape_scale = org_bi.custom_shape_scale
			tweak_bone.custom_shape_transform = org_bi.custom_shape_transform
			tweak_bone.use_custom_shape_bone_size = org_bi.use_custom_shape_bone_size
			tweak_bone.show_wire = org_bi.show_wire
			if org_bi.custom_shape:
				self.add_to_widget_collection(org_bi.custom_shape)

		if self.params.CR_tweak_group:
			# TODO: This code overlaps a lot with cloud_bone, maybe it could be shared somehow?
			# In order for the bone group to transfer to the generated rig, we need to add a bone set to the generator.
			meta_bg = meta_bone.bone_group
			if meta_bg:
				bg_name = meta_bg.name
				
				new_set = BoneSet(self,
					ui_name = bg_name
					,bone_group = bg_name
					,layers = meta_bone.bone.layers[:]
					,normal = meta_bg.colors.normal[:]
					,active = meta_bg.colors.active[:]
					,select = meta_bg.colors.select[:]
					,defaults = self.defaults
				)
				self.generator.bone_sets.append(new_set)
				tweak_bone.bone_group = bg_name

		if self.params.CR_tweak_layers:
			tweak_bone.layers = meta_bone.bone.layers[:]

		if self.params.CR_tweak_ik_settings:
			tweak_bone.ik_stretch = org_bi.ik_stretch
			tweak_bone.lock_ik_x = org_bi.lock_ik_x
			tweak_bone.lock_ik_y = org_bi.lock_ik_y
			tweak_bone.lock_ik_z = org_bi.lock_ik_z
			tweak_bone.ik_stiffness_x = org_bi.ik_stiffness_x
			tweak_bone.ik_stiffness_y = org_bi.ik_stiffness_y
			tweak_bone.ik_stiffness_z = org_bi.ik_stiffness_z
			tweak_bone.use_ik_limit_x = org_bi.use_ik_limit_x
			tweak_bone.use_ik_limit_y = org_bi.use_ik_limit_y
			tweak_bone.use_ik_limit_z = org_bi.use_ik_limit_z
			tweak_bone.ik_min_x = org_bi.ik_min_x
			tweak_bone.ik_max_x = org_bi.ik_max_x
			tweak_bone.ik_min_y = org_bi.ik_min_y
			tweak_bone.ik_max_y = org_bi.ik_max_y
			tweak_bone.ik_min_z = org_bi.ik_min_z
			tweak_bone.ik_max_z = org_bi.ik_max_z

		if self.params.CR_tweak_bbone_props:
			tweak_bone.bbone_segments = org_bi.bbone_segments
			tweak_bone.bbone_x = org_bi.bbone_x
			tweak_bone.bbone_z = org_bi.bbone_z

		# Parenting
		bendy_parenting(tweak_bone, self.params.CR_copy_parent)

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_tweak_show_settings = BoolProperty(
			name		 = "Tweak Settings"
			,description = "Reveal settings for the cloud_tweak rig type"
		)

		params.CR_tweak_constraints_additive = BoolProperty(
			name="Additive Constraints"
			,description="Add the constraints of this bone to the generated bone's constraints. When disabled, we replace the constraints instead"
			,default=True
		)
		params.CR_tweak_transforms = BoolProperty(
			 name="Transforms"
			,description="Replace the matching generated bone's transforms with this bone's transforms" # An idea: when this is False, let the generation script affect the metarig - and move this bone, to where it is in the generated rig.
			,default=False
		)
		params.CR_tweak_locks = BoolProperty(
			 name="Locks"
			,description="Replace the matching generated bone's transform locks with this bone's transform locks"
			,default=True
		)
		params.CR_tweak_rot_mode = BoolProperty(
			 name="Rotation Mode"
			,description="Set the matching generated bone's rotation mode to this bone's rotation mode"
			,default=False
		)
		params.CR_tweak_shape = BoolProperty(
			 name="Bone Shape"
			,description = "Replace the matching generated bone's shape with this bone's shape"
			,default=False
		)
		params.CR_tweak_group = BoolProperty(
			 name="Bone Group"
			,description="Replace the matching generated bone's group with this bone's group"
			,default=False
		)
		params.CR_tweak_layers = BoolProperty(
			 name="Layers"
			,description="Set the generated bone's layers to this bone's layers"
			,default=False
		)
		params.CR_tweak_ik_settings = BoolProperty(
			 name="IK Settings"
			,description="Copy IK settings from this bone to the generated bone"
			,default=False
		)
		params.CR_tweak_bbone_props = BoolProperty(
			name="B-Bone Settings"
			,description="Copy B-Bone settings from this bone to the generated bone"
			,default=False
		)
		add_parent_param(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_tweak_show_settings'): return layout

		draw_parent_param(layout, context, params)
		layout.prop(params, "CR_tweak_constraints_additive")
		layout.prop(params, "CR_tweak_transforms")
		layout.prop(params, "CR_tweak_locks")
		layout.prop(params, "CR_tweak_rot_mode")
		layout.prop(params, "CR_tweak_shape")
		layout.prop(params, "CR_tweak_group")
		layout.prop(params, "CR_tweak_layers")
		layout.prop(params, "CR_tweak_ik_settings")
		layout.prop(params, "CR_tweak_bbone_props")

		return layout

class Rig(CloudTweakRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)