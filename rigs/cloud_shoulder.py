from bpy.props import BoolProperty, EnumProperty

from math import pi

from .cloud_fk_chain import CloudFKChainRig

class CloudShoulderRig(CloudFKChainRig):
	"""A single bone control to connect an arm to a spine."""

	def initialize(self):
		super().initialize()
		"""Gather and validate data about the rig."""
		if len(self.bones.org.main)>1:
			print(f"""Shoulder rig on {self.base_bone} has a chain of more than a single bone. 
				   The rig only requires one bone, the rest will be unaffected!""")

	def prepare_bones(self):
		super().prepare_bones()
		self.prepare_fk_shoulder()

	def prepare_fk_shoulder(self):
		control = self.fk_chain[0]
		control.custom_shape = self.load_widget("Clavicle")
		self.register_parent(control, self.side_prefix.capitalize() + " Shoulder")
		shoulder_rot = int(self.params.CR_shoulder_up_axis)
		if shoulder_rot != 0:
			dsp_bone = self.create_dsp_bone(control, center=False)
			dsp_bone.roll += pi/2*shoulder_rot

		parent = self.get_bone(self.base_bone).parent
		if parent:
			control.parent = parent.name

	##############################
	# Parameters

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
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
	def cloud_params_ui(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().cloud_params_ui(layout, params)
		cls.disable_row('CR_fk_chain_display_center')

		if not cls.cloud_dropdown_ui(layout, params, "CR_shoulder_show_settings"): return layout

		layout.prop(params, 'CR_shoulder_up_axis')

		return layout

class Rig(CloudShoulderRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_shoulder")