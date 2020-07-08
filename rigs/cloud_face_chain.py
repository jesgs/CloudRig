from bpy.props import BoolProperty, IntProperty

from .cloud_utils import make_name, slice_name
from .cloud_chain import CloudChainRig
"""TODO:
Come up with a smart way to allow nearby STR chains to affect each other.
Use a separate cloud_face_glue rig type if needed, but maybe it can be done from here.
"""
class CloudFaceChainRig(CloudChainRig):
	"""Chain with cartoony squash and stretch controls, with modifications and extra features for face rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_face_chain rigs from the generator, excluding self.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if isinstance(rig, type(self)) and rig!=self:
				self.chain_rigs.append(rig)

		for rig in self.chain_rigs:
			print(rig.base_bone)

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		# This bone set is special in that its .new() function should never be called, and therefore it never creates any bones.
		# However, pre-existing STR bones who then had a merged control created for them will be assigned the bone group and layer of this BoneSet.
		self.sub_controls = self.ensure_bone_set("Sub Controls")
		self.merged_controls = self.ensure_bone_set("Merged Controls")

	def prepare_bones(self):
		super().prepare_bones()
		if self.params.CR_face_chain_merge:
			self.merge_controls()

	def ensure_parent_control(self, bones):
		"""Ensure that all bones share the same parent control. If this is not the case, create it and parent them."""

		# Check the bones' parents to see if the desired control was already created.
		parent = None
		for b in bones:
			if b.parent.name.startswith("STR-I"):
				parent = b.parent
				break

		if not parent:
			# Naming this control will be non-trivial.		
			bases_nonunique = [slice_name(b.name)[1] for b in bones]
			bases = set(bases_nonunique)
			suffixes = set([self.generator.suffix_separator.join(slice_name(b.name)[2]) for b in bones])
			bone_name = make_name(["STR", "I"], "+".join(bases), suffixes)
			parent = self.merged_controls.new(
				name = bone_name
				,source = bones[0]
				,custom_shape = self.load_widget('Cube')
				,custom_shape_scale = bones[0].custom_shape_scale
			)
		for b in bones:
			b.parent = parent

	def merge_controls(self):
		# For each main STR control in this rig
		#   For each main STR control in every other rig
		#	   If the two are in the same position
		#		   Ensure a parent control(not sure about the name)
		#		   Move both to the layers of the Merged Controls bone set.

		merge_threshold = 0.1
		sets_to_merge = []
		for my_main in self.main_str_bones:
			set_to_merge = [my_main]
			for other_rig in self.chain_rigs:
				if not hasattr(other_rig, "main_str_bones"): continue
				for other_main in other_rig.main_str_bones:
					if (my_main.head-other_main.head).length < merge_threshold:
						set_to_merge.append(other_main)
			if len(set_to_merge)>1:
				sets_to_merge.append(set_to_merge)
		
		for bones in sets_to_merge:
			self.ensure_parent_control(bones)
			for b in bones:
				b.layers = self.sub_controls.layers[:]
				# b.custom_shape = self.load_widget('Cube')

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Sub Controls", preset=1,	default_layers=[cls.default_layers('MCH')], override='MCH')
		cls.define_bone_set(params, "Merged Controls", preset=8,	default_layers=[cls.default_layers('STRETCH')])

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)

		params.CR_show_face_chain_parameters = BoolProperty(
			name		 = "Face Chain Settings"
			,description = "Reveal settings for the cloud_face_chain rig type"
		)
		params.CR_face_chain_merge = BoolProperty(
			name		 = "Merge Controls"
			,description = "If any controls of this rig overlap with another, create a parent control that owns all overlapping controls, and hide the overlapping controls on a different layer"
			,default	 = True
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_face_chain_parameters"): return layout

		layout.prop(params, "CR_face_chain_merge")

		return layout

class Rig(CloudFaceChainRig):
	pass