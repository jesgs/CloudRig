from bpy.props import BoolProperty, StringProperty
from .cloud_base import Component_Base
from .cloud_copy import Component_CopyBone
from ..rig_component_features.bone import BoneInfo

class CloudJawRig(Component_CopyBone):
	"""Jaw rig with cartoony features."""

	"""Functionality TODO:
		- (TODO) Chin Resists Jaw (Optional, only if a chin bone is specified...)
		- (Done) MSTR Mouth control (which should be controlled by Action set-ups rather than manually)
		- (Done) Teeth Follow Mouth: (should be "Teeth Follow MSTR-Lips)
		- (Done) A bone that the lower teeth and tongue can be parented to, which has an Armature constraint with the drivers found on Ellie.
			Let's call this MCH-LowerJaw-{JawName} this would be the current MSTR-Mouth_Lower, which copies local transforms of Jaw, and is parented to MSTR-Mouth.
		- (Done) Jaw Squash:
		This is the current MSTR-Head_Bottom and MSTR-Head_Bottom_Squash controls.
		Rigger would have to select a bone, along whose length, these jaw squash controls can be created.
	"""

	"""Cleanup TODO:
		- Currently a lot of bones are required to be parented in a specific way for the Jaw rig, and be assigned the cloud_copy rig type, which comes with confusing options.
			Would be better to not have to assign a Rigify Type to these bones.
			They could all be parented to the jaw bone (otherwise throw useful error) and then loaded into BoneInfo instances during initialize() by making the load_org_bones() function in cloud_base more flexible.

		- Bone shapes & layers
	"""

	"""Hierarchy:
		MSTR-Head_Bottom (CR_jaw_lower_face_bone)
			Purpose: Owns entire lower half of the face, but not the back of the head. Currently exposed to animators, but doesn't have to be.
			Parent: DEF-Head (outside this rig)
			Constraints: None
			Placement: Such that it favors swinging the mouth side-to-side like a pendulum: quite high above lips
		MSTR-Head_Bottom_Squash (should be MSTR-LowerFace_Squash) (CR_jaw_squash_bone)
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
		Jaw (bone that owns the rig component)
			Purpose: Animator control to open the mouth.
			Parent: MSTR-H-Head_Bottom
			Constraints: None
			Placement: From side view: Height at the lips, depth almost reaching earlobe.
		MSTR-Mouth (should be MSTR-Lips) (CR_jaw_mouth_bone)
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
		# Not yet sure what's the best way to make the user define the components of the jaw rig
		# and therefore not sure what's the best way to grab the bone info here.
		# For now, let's do this: The other rig components are expected to be cloud_copy components, 
		# who are higher in the hierarchy than the jaw rig (will be odd for the chin...)
		# so that they are generated first, so we can be sure that their BoneInfo exists.

		# For now we demand all the bones to exist, but in future some functionalities should be optional, 
		# so the rig is easier to set up.

		jaw_bi = self.bones_org[0]
		lower_face_bi = self.generator.find_bone_info(self.params.CR_jaw_lower_face_bone)
		if not lower_face_bi:
			self.raise_metarig_error("Lower Face Bone not found!")
		face_squash_bi = self.generator.find_bone_info(self.params.CR_jaw_squash_bone)
		if not face_squash_bi:
			self.raise_metarig_error("Squash Bone not found!")
		lower_face_squasher = self.create_face_squasher(face_squash_bi, lower_face_bi, jaw_bi)
		chin_bi = self.generator.find_bone_info(self.params.CR_jaw_chin_bone)
		if not chin_bi:
			self.raise_metarig_error("Chin Bone not found!")
		mouth_bi = self.generator.find_bone_info(self.params.CR_jaw_mouth_bone)
		if not mouth_bi:
			self.raise_metarig_error("Mouth Master Bone not found!")

		lower_jaw = self.make_lower_jaw(jaw_bi, mouth_bi)

		jaw_bi.parent = lower_face_squasher
		mouth_bi.parent = lower_face_squasher

		self.setup_teeth_follow_mouth(jaw_bi, lower_face_bi, mouth_bi, lower_jaw)

	def make_lower_jaw(self, jaw_bi, mouth_bi) -> BoneInfo:
		lower_jaw = self.bone_sets['Mechanism Bones'].new(
			name = "LowerJaw-" + jaw_bi.name
			,source = jaw_bi
			,parent = mouth_bi
		)
		lower_jaw.add_constraint('COPY_TRANSFORMS'
			,subtarget = jaw_bi
		)
		return lower_jaw

	def create_face_squasher(self, face_squash_bi, lower_face_bi, jaw_bi) -> BoneInfo:
		lower_face_squasher = self.bone_sets['Jaw Controls'].new(
			name = "SQ-" + face_squash_bi.name
			,source = face_squash_bi
			,roll = face_squash_bi.roll	# TODO: I don't think this matters.
			,parent = lower_face_bi
			,custom_shape = self.ensure_widget('Curve_Handle')
		)
		lower_face_squasher.reverse()
		stretch_con = lower_face_squasher.add_constraint('STRETCH_TO'
			,subtarget = face_squash_bi
		)
		# Create custom property for face squash volume preservation (a toggle for now)
		info = {
			"prop_bone"			: jaw_bi,
			"prop_id" 			: 'preserve_volume',
		}
		# Store UI info & create custom prop
		self.add_ui_data("Face", "Preserve Volume", info, default=1)
		for prop in ['use_bulge_min', 'use_bulge_max']:
			stretch_con.drivers.append({
				'prop' : prop
				,'variables' : [(jaw_bi.name, 'preserve_volume')]
				,'expression' : '1-var'
			})

		return lower_face_squasher

	def setup_teeth_follow_mouth(self, jaw_bi, lower_face_bi, mouth_bi, lower_jaw):
		# Set up Teeth Follow Mouth toggle
		info = {
			'prop_bone' : jaw_bi
			,'prop_id' : 'teeth_follow_mouth'
		}
		self.add_ui_data("Face", "Teeth Follow Mouth", info, default=1.0)
		teeth_upper_root = self.generator.find_bone_info(self.params.CR_jaw_teeth_upper_bone)
		if not teeth_upper_root:
			self.raise_metarig_error("Upper Teeth not found!")
		teeth_lower_root = self.generator.find_bone_info(self.params.CR_jaw_teeth_lower_bone)
		if not teeth_lower_root:
			self.raise_metarig_error("Lower Teeth not found!")
		teeth = [teeth_upper_root, teeth_lower_root]
		arm_con = teeth_upper_root.add_constraint('ARMATURE'
			,targets = [
				{
					"subtarget" : lower_face_bi.parent # This is usually DEF-Head
				},
				{
					"subtarget" : mouth_bi
				}
			]
		)
		arm_con = teeth_lower_root.add_constraint('ARMATURE'
			,targets = [
				{
					"subtarget" : jaw_bi # This is usually DEF-Head
				},
				{
					"subtarget" : lower_jaw
				}
			]
		)
		for teeth_root in teeth:
			arm_con = teeth_root.constraint_infos[0]
			arm_con.drivers.append({
				'prop' : 'targets[0].weight'
				,'variables' : [(jaw_bi.name, 'teeth_follow_mouth')]
				,'expression' : '1-var'
			})
			arm_con.drivers.append({
				'prop' : 'targets[1].weight'
				,'variables' : [(jaw_bi.name, 'teeth_follow_mouth')]
			})

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Jaw Controls', preset=2,	default_layers=[cls.DEFAULT_LAYERS.FACE_MAIN])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_jaw_lower_face_bone = StringProperty(
			name		 = "Lower Face Bone"
			,description = "Optional. Select a bone to place the Lower Face control. This bone should be placed for best effect when rotating side to side, to swing the cartoony jaw around like a pendulum"
		)
		params.CR_jaw_squash_bone = StringProperty(
			name		 = "Squash Bone"
			,description = "Optional. Select a bone to place the Lower Face Squash control. This will squash from its head to its tail, so place it carefully for best effect"
		)
		params.CR_jaw_chin_bone = StringProperty(
			name		 = "Chin Bone"
			,description = 'Optional. Select a bone to place the Chin control. You can parent the chin area to that bone, and control the influence of the jaw on it via a "Chin Resist Jaw" property'
		)
		params.CR_jaw_mouth_bone = StringProperty(
			name		 = "Mouth Master"
			,description = 'Select a bone to place the Mouth Master control. You can parent the chin area to that bone, and control the influence of the jaw on it via a "Chin Resist Jaw" property'
		)
		params.CR_jaw_teeth_follow = BoolProperty(
			name		 = "Teeth Follow Mouth Master"
			,description = 'Create a Lower/UpperJaw helper bone and a "Teeth Follow MSTR-Lips" slider. You should parent the lower teeth to this helper bone to allow the teeth to be parented to the mouth master control'
			,default	 = False
		)
		params.CR_jaw_teeth_upper_bone = StringProperty(
			name		 = "Upper Teeth Root"
			,description = 'Select the cloud_copy bone that acts as the root of the upper teeth'
		)
		params.CR_jaw_teeth_lower_bone = StringProperty(
			name		 = "Lower Teeth Root"
			,description = 'Select the cloud_copy bone that acts as the root of the upper teeth'
		)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""

		layout.label(text="The cloud_jaw rig type is still in experimental stage.")
		layout.label(text="Compatibility will break, don't use for anything serious!")
		cls.draw_prop_search(layout.row(), params, "CR_jaw_lower_face_bone", context.object.data, "bones")
		cls.draw_prop_search(layout.row(), params, "CR_jaw_squash_bone", context.object.data, "bones")
		cls.draw_prop_search(layout.row(), params, "CR_jaw_chin_bone", context.object.data, "bones")
		cls.draw_prop_search(layout.row(), params, "CR_jaw_mouth_bone", context.object.data, "bones")

		cls.draw_prop(layout, params, 'CR_jaw_teeth_follow')
		if params.CR_jaw_teeth_follow:
			cls.draw_prop_search(layout.row(), params, "CR_jaw_teeth_upper_bone", context.object.data, "bones")
			cls.draw_prop_search(layout.row(), params, "CR_jaw_teeth_lower_bone", context.object.data, "bones")


# Uncomment the next two lines to make this rig show up in Blender.
class RigComponent(CloudJawRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)