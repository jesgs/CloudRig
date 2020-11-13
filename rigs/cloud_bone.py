import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty
from ..bone import BoneInfo, BoneSet

from ..rigs.cloud_base import DefaultLayers
from .cloud_base import CloudBaseRig

"""TODO
Split up into cloud_tweak for the tweaking functionality, maybe one can extend the other idk.
Rework the entire thing so it uses BoneInfo instead of doing things normally? Not sure, should think about pros and cons.

Whoa, cloud_aim could actually inherit from this class... in theory, that should be good.

Could also move parent switching mechanism and root bone from cloud_aim to here instead.
"""

class CloudBoneRig(CloudBaseRig):
	"""Create a single bone in the generated rig."""

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
		
		# Find parent bone
		parent_name = self.params.CR_bone_parent
		parent_bone = self.generator.find_bone_info(parent_name)
		if not parent_bone:
			self.generator.logger.log(
				"Parent not found"
				,owner_bone = self.base_bone
				,description = f"Target parent bone {parent_name} not found. If this bone does actually exist, you should make sure that this cloud_bone rig is lower in the parenting hierarchy than the rig that generated the target bone."
			)
			# Still try string-based parenting, which is not ideal but ohwell.
			bi.parent = parent_name
			return

		else:
			bi.parent = parent_bone
			# If parent bone has BBone segments, use Armature constraint for parenting.
			if parent_bone.bbone_segments > 1:
				arm_con = bi.add_constraint('ARMATURE', index=-len(bi.constraint_infos)
					,use_deform_preserve_volume = True
					,targets = [
						{
							"subtarget" : parent_name
						}
					]
				)

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

		params.CR_bone_show_settings = BoolProperty(
			name		 = "Bone Settings"
			,description = "Reveal settings for the cloud_bone rig type"
		)

		params.CR_bone_parent = StringProperty(
			 name="Parent"
			,description="When this is not an empty string, set the parent to the bone with this name"
			,default=""
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_bone_show_settings'): return layout

		pb = bpy.context.active_pose_bone

		layout.prop(params, "CR_bone_parent")
		layout.prop(pb.bone, "use_deform", text="Create Deform Bone")

		return layout

class Rig(CloudBoneRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)