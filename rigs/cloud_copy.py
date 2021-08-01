import bpy
from bpy.props import BoolProperty
from ..rig_features.bone_set import BoneSet

from .cloud_base import CloudBaseRig

"""TODO
cloud_aim could maybe inherit from this?

Could also move parent switching mechanism and root bone from cloud_aim to here instead.
Better yet, to cloud_base!
"""

class CloudCopyRig(CloudBaseRig):
	"""Copy this bone to the generated rig."""
	always_use_custom_props = True

	def initialize(self):
		super().initialize()

		self.orgless_name = self.base_bone.replace("ORG-", "")

		# If the metarig bone has a Child Of or Armature constraint, don't do any parenting logic.
		self.do_parenting = True
		for c in self.meta_base_bone.constraints:
			if c.type in ('CHILD_OF', 'ARMATURE'):
				self.do_parenting = False

		self.create_deform_bone = self.meta_base_bone.bone.use_deform

	def create_bone_infos(self):
		super().create_bone_infos()
		bi = self.bones_org[0]

		# Strip ORG from bone's name (@name.setter takes care of everything)
		bi.name = self.orgless_name

		if not bi.use_custom_shape_bone_size:
			bi.custom_shape_scale /= bi.bbone_width * 10 * self.scale

		meta_bone = self.meta_bone(bi.name)
		bi.layers = meta_bone.bone.layers[:]
		bi.use_deform = False
		if not meta_bone:
			self.add_log_bug("Bone not found in MetaRig", trouble_bone=bi.name)
			return

		if meta_bone.custom_shape:
			self.add_to_widget_collection(meta_bone.custom_shape)

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
			def_bone = self.make_def_bone(bi, self.bones_def)
			def_bone.parent = bi

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

	##############################
	# Parameters

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		pb = context.active_pose_bone
		layout.prop(pb.bone, 'use_deform', text="Create Deform Bone")

class Rig(CloudCopyRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)