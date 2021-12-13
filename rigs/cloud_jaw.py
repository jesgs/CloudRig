from bpy.props import BoolProperty, StringProperty
from .cloud_base import CloudBaseRig

class CloudJawRig(CloudBaseRig):
	"""Jaw rig with cartoony features."""

	"""Functionality TODO:
		- Chin Resists Jaw (Optional, only if a chin bone is specified...)
		- MSTR Mouth control (which should be controlled by Action set-ups rather than manually)
		- Teeth Follow Mouth: (should be "Teeth Follow MSTR-Lips)
		- A bone that the lower teeth and tongue can be parented to, which has an Armature constraint with the drivers found on Ellie.
			Let's call this MCH-LowerJaw-{JawName} this would be the current MSTR-Mouth_Lower, which copies local transforms of Jaw, and is parented to MSTR-Mouth.
		- Jaw Squash:
		This is the current MSTR-Head_Bottom and MSTR-Head_Bottom_Squash controls.
		Rigger would have to select a bone, along whose length, these jaw squash controls can be created.
	"""

	"""Hierarchy:
		MSTR-Head_Bottom
			Purpose: Owns entire lower half of the face, but not the back of the head. Currently exposed to animators, but doesn't have to be.
			Parent: DEF-Head (outside this rig)
			Constraints: None
			Placement: Such that it favors swinging the mouth side-to-side like a pendulum: quite high above lips
		MSTR-Head_Bottom_Squash (should be MSTR-LowerFace_Squash)
			Purpose: Control to squash the lower face.
			Parent: MSTR-Head_Bottom
			Constraints: None
			Placement: Such that it favors squashing the lower face: From underneath the chin to the top of the top teeth.
		MSTR-H-Head_Bottom (should be MCH-LowerFace_Squash)
			Purpose: Squashes the jaw
			Parent: MSTR-Head_Bottom
			Constraints:
				Stretch To: MSTR-Head_Bottom_Squash
					Drivers on use_bulge_min and use_bulge_max hooked up to 'Face Squash' property.
					TODO: Make it a slider instead, call it "Jaw Volume" instead.
			Placement: Inverse of MSTR-Head_Bottom_Squash
		Jaw
			Purpose: Animator control to open the mouth.
			Parent: MSTR-H-Head_Bottom
			Constraints: None
			Placement: From side view: Height at the lips, depth almost reaching earlobe.
		MSTR-Mouth (should be MSTR-Lips)
			Purpose: Move the entire mouth around the face. On Ellie's rig, this is a directly exposed control, but I would mask it behind an Action control.
			Parent: MSTR-H-Head_Bottom
			Constraints: None (Future: Action)
			Placement: Somewhere along the jaw bone, but probably not as deep; Want decent behaviour on all rotation axes. (But with an Action set-up it won't matter that much, just results in easier Action authoring)
		MSTR-Mouth_Lower (should be MCH)
			Placement: Match Jaw
			Purpose: The control that owns the entire lower lip by default should be parented to this. (MSTR-Lip_Lower)
			Parent: MSTR-Mouth
			Constraints:
				Copy Transforms (Local): Jaw
	"""

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()
		if self.params.CR_template_use_control:
			self.make_ctr_bone(self.bones_org[0])

	def make_ctr_bone(self, bone):
		ctr_bone = self.bone_sets['Template Bones'].new(
			name = bone.name.replace('ORG', "CTR")
			,source = bone
			,custom_shape = self.ensure_widget('Circle')
			,parent = bone.parent
		)
		copy_trans = bone.add_constraint('COPY_TRANSFORMS', subtarget=ctr_bone.name)
		return ctr_bone

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Template Bones', preset=1,	default_layers=[cls.DEFAULT_LAYERS.IK_MAIN])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_jaw_chin_bone = StringProperty(
			name		 = "Chin Bone"
			,description = 'Optional. Select a bone to place the Chin control. You can parent the chin area to that bone, and control the influence of the jaw on it via a "Chin Resist Jaw" property'
		)
		params.CR_jaw_lower_face_bone = StringProperty(
			name		 = "Lower Face Bone"
			,description = "Optional. Select a bone to place the Lower Face control"
		)
		params.CR_jaw_squash_bone = StringProperty(
			name		 = "Squash Bone"
			,description = "Optional. Select a bone to place the Lower Face Squash control"
		)
		params.CR_jaw_teeth_follow = BoolProperty(
			name		 = "Teeth Follow MSTR-Lips"
			,description = 'Create a Lower/UpperJaw helper bone and a "Teeth Follow MSTR-Lips" slider. Parent the lower teeth to this helper bone to allow the teeth to be parented to the mouth master control.'
			,default	 = False
		)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)

		cls.draw_prop(layout, params, 'CR_template_use_control')

# Uncomment the next two lines to make this rig show up in Blender.
class Rig(CloudJawRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)