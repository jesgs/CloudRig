from bpy.props import BoolProperty, EnumProperty

from math import pi, radians

from .cloud_fk_chain import CloudFKChainRig

class CloudShoulderRig(CloudFKChainRig):
	"""A single bone control to connect an arm to a spine."""

	forced_params = {
		'CR_fk_chain_display_center' : False
	}

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""
		if self.bone_count>1:
			print(f"""Shoulder rig on {self.base_bone} has a chain of more than a single bone.
				   The rig only requires one bone, the rest will be unaffected!""")

	def create_bone_infos(self):
		super().create_bone_infos()
		self.prepare_fk_shoulder()

	def prepare_fk_shoulder(self):
		control = self.bone_sets['FK Controls'][0]
		control.custom_shape = self.ensure_widget("Clavicle")
		shoulder_rot = radians ( int(self.params.CR_shoulder_up_axis) * 90 )

		control.custom_shape_rotation_euler.y = shoulder_rot

		parent = self.get_bone(self.base_bone).parent
		if parent:
			control.parent = parent.name

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_shoulder_show_settings = BoolProperty(name="Shoulder Settings")
		params.CR_shoulder_up_axis = EnumProperty(
			name = "Up Axis"
			,description = "Rotate the bone shape to align with this axis of the bone"
			,items = [
				("0", '+Z', "Do not rotate the bone shape", 0),
				("1", '+X', "Rotate bone shape by 90 degrees", 1),
				("2", '-Z', "Rotate bone shape by 180 degrees", 2),
				("3", '-X', "Rotate bone shape by -90 degrees", 3),
			]
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_shoulder_show_settings"): return layout

		cls.draw_prop(layout, params, 'CR_shoulder_up_axis')

		return layout

class Rig(CloudShoulderRig):
	pass

from ..metarigs.load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)