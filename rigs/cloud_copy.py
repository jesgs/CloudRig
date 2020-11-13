import bpy
from bpy.props import BoolProperty, StringProperty
from ..bone import BoneInfo, BoneSet

from .cloud_base import CloudBaseRig

"""TODO
cloud_aim could maybe inherit from this?

Could also move parent switching mechanism and root bone from cloud_aim to here instead.
"""

def bendy_parenting(bone, parent_name):
	if parent_name=="": return
	generator = bone.bone_set.rig.generator
	parent_bone = generator.find_bone_info(parent_name)
	if not parent_bone:
		bone.bone_set.rig.add_log(
			"Parent not found"
			,trouble_bone = bone.name
			,description = f"Target parent bone {parent_name} not found. If this bone does actually exist, you should make sure that this cloud_copy/tweak rig is lower in the parenting hierarchy than the rig that generated the target bone."
		)
		# Still try string-based parenting, which is not ideal but ohwell.
		bone.parent = parent_name
		return
	else:
		bone.parent = parent_bone
		# If parent bone has BBone segments, use Armature constraint for parenting.
		if parent_bone.bbone_segments > 1:
			bone.add_constraint('ARMATURE', index=-len(bone.constraint_infos)
				,use_deform_preserve_volume = True
				,targets = [
					{
						"subtarget" : parent_bone.name
					}
				]
			)

def add_parent_param(params):
	params.CR_copy_parent = StringProperty(
		name="Parent"
		,description="When this is not an empty string, set the parent to the bone with this name"
		,default=""
	)

def draw_parent_param(layout, context, params):
	metarig = context.object
	rig = metarig.data.rigify_target_rig
	if rig:
		layout.prop_search(params, 'CR_copy_parent', rig.pose, 'bones')
		parent_bone = rig.pose.bones.get(params.CR_copy_parent)
		if parent_bone and parent_bone.bone.bbone_segments > 1:
			split=layout.row().split(factor=0.4)
			split.row()
			split.label(text="Bendy Bone, will use Armature Constraint")
	else:
		layout.prop(params, 'CR_copy_parent')
	return layout

class CloudCopyRig(CloudBaseRig):
	"""Copy this bone to the generated rig."""

	def initialize(self):
		super().initialize()

		self.orgless_name = self.base_bone.replace("ORG-", "")

		# If the metarig bone has a Child Of or Armature constraint, don't do any parenting logic.
		self.do_parenting = True
		meta_pose_bone = self.generator.metarig.pose.bones.get(self.orgless_name)
		for c in meta_pose_bone.constraints:
			if c.type in ('CHILD_OF', 'ARMATURE'):
				self.do_parenting = False

		self.create_deform_bone = meta_pose_bone.bone.use_deform

	def reparent_bone(self, child: BoneInfo):
		"""Overrides CloudMechanismMixin."""
		return None

	def prepare_bones(self):
		super().prepare_bones()
		bi = self.org_chain[0]
		if not bi.use_custom_shape_bone_size:
			bi.custom_shape_scale /= bi.bbone_width * 10 * self.scale

		# Strip ORG from bone's name (@name.setter takes care of everything)
		bi.name = self.orgless_name

		meta_bone = self.meta_bone(bi.name)
		bi.layers = meta_bone.bone.layers[:]
		bi.use_deform = False
		if not meta_bone:
			self.add_log_bug("Bone not found in MetaRig", trouble_bone=bi.name)
			return

		if bi.rotation_mode == 'QUATERNION':
			self.add_log("Quaternion rotation"
				,trouble_bone = self.base_bone
				,description = f"{meta_bone.name} is on Quaternion rotation mode. Animator-facing controls should be set to Euler!"
				,icon = 'GIZMO'
				,operator = 'pose.cloudrig_troubleshoot_rotationmode'
				,op_kwargs = {'bone_name' : self.orgless_name}
				,op_text = f"Set {meta_bone.name} to Euler"
			)
			bi.rotation_mode = 'XYZ'

		if self.create_deform_bone:
			# Make a copy with DEF- prefix, as our deform bone.
			def_bone = self.make_def_bone(bi, self.def_chain)
			def_bone.parent = bi

		# Relink constraints
		for c in bi.constraint_infos:
			c.relink()
			# Relink constraint drivers
			for d in c.drivers:
				self.relink_driver(d)

		# Relink bone drivers
		for d in bi.drivers:
			self.relink_driver(d)

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
			bi.bone_group = bg_name

		# Parenting
		bendy_parenting(bi, self.params.CR_copy_parent)

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup"""
		super().add_parameters(params)

		params.CR_copy_show_settings = BoolProperty(
			name		 = "Copy Settings"
			,description = "Reveal settings for the cloud_copy rig type"
		)
		add_parent_param(params)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_copy_show_settings'): return layout

		pb = bpy.context.active_pose_bone

		draw_parent_param(layout, context, params)
		layout.prop(pb.bone, 'use_deform', text="Create Deform Bone")

		return layout

class Rig(CloudCopyRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)