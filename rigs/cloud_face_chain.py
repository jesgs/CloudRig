from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

from .cloud_chain import CloudChainRig

class CloudFaceChainRig(CloudChainRig):
	"""Chain with cartoony squash and stretch controls, with modifications and extra features for face rigs."""

	def initialize(self):
		super().initialize()

		# Gather all cloud_face_chain rigs from the generator, excluding self.
		self.chain_rigs = []
		for rig in self.generator.rig_list:
			if isinstance(rig, type(self)):
				self.chain_rigs.append(rig)

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		# This bone set is special in that its .new() function should never be called, and therefore it never creates any bones.
		# However, pre-existing STR bones who then had a merged control created for them will be assigned the bone group and layer of this BoneSet.
		self.sub_controls = self.ensure_bone_set("Sub Controls")
		self.merged_controls = self.ensure_bone_set("Merged Controls")

	def prepare_bones(self):
		super().prepare_bones()

		# Move constraints from ORG bones to main STR bones and relink them
		if self.params.CR_face_chain_relink:
			self.move_and_relink_constraints()

		if self.params.CR_face_chain_merge:
			self.merge_controls()

	def move_and_relink_constraints(self):
		for i, org in enumerate(self.org_chain):
			for c in org.constraint_infos[:]:
				if 'TAIL' in c.name:
					self.main_str_bones[i+1].constraint_infos.append(c)
				else:
					self.main_str_bones[i].constraint_infos.append(c)
				org.constraint_infos.remove(c)
				c.relink()

	def merge_controls(self):
		# For each main STR control in this rig
		#   For each main STR control in every other rig
		#	   If the two are in the same position
		#		   Ensure a parent control
		#		   Move both to the layers of the Sub Controls bone set.

		merge_threshold = 0.000001
		sets_to_merge = []
		for my_main in self.main_str_bones:
			set_to_merge = [my_main]
			for other_rig in self.chain_rigs:
				if not hasattr(other_rig, "main_str_bones"): continue
				for other_main in other_rig.main_str_bones:
					if other_main == my_main: continue
					if (my_main.head-other_main.head).length < merge_threshold:
						set_to_merge.append(other_main)
			if len(set_to_merge)>1:
				sets_to_merge.append(set_to_merge)

		for bones in sets_to_merge:
			self.ensure_parent_control(bones)
			for b in bones:
				b.layers = self.sub_controls.layers[:]

	def ensure_parent_control(self, bones):
		""" Ensure that all bones share the same parent control. 
			If this is not the case, create it and parent them.
		"""

		# Check the bones' parents to see if the desired control was already created.
		parent = None
		for b in bones:
			if b.parent.name.startswith("STR-I"):
				parent = b.parent
				break

		if not parent:
			combined_name = self.naming.combine_names(bones)
			slices = self.naming.slice_name(combined_name)
			# Discard prefixes, put STR-I.
			bone_name = self.naming.make_name(["STR", "I"], slices[1], slices[2])
			parent = self.merged_controls.new(
				name = bone_name
				,source = bones[0]
				,custom_shape = self.load_widget('Cube')
				,custom_shape_scale = bones[0].custom_shape_scale
			)

		# If bones are in the center, flatten them to make sure they produce a clean curvature.
		if abs(parent.head.x) < 0.001:
			parent.vector = Vector((0, 0, parent.length))	# TODO: be nicer to make it aligned with whatever axis the rest of the bones are closest to, instead of arbitrarily the up axis.
			parent.roll = 0
			for b in bones:
				b.vector = self.flat_vector(b.vector)

		for b in bones:
			b.parent = parent # This will be set to None later by the generator when it sees the Armature constraint, just using it for easy access here.
			par_con_name = "Armature (Parenting affects local matrix)"
			if b.container.rig.params.CR_smooth_spline:
				b.add_constraint('ARMATURE', name=par_con_name, index=0, 
					targets = [
						{
							"subtarget" : parent.name
						},
					]
				)
			# Move constraints except the above one to the merged control
			for c in b.constraint_infos[:]:
				if c.name==par_con_name: continue
				parent.constraint_infos.append(c)
				b.constraint_infos.remove(c)

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		""" Create parameters for this rig's bone sets. """
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Sub Controls", preset=1,	default_layers=[cls.default_layers('MCH')])
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
		params.CR_face_chain_relink = BoolProperty(
			name		 = "Relink Constraints"
			,description = "Constraints on this chain will be relinked to the corresponding STR controls that are created for them. For the final bone of the chain, constraints intended for the final control should be prefixed with \"TAIL-\""
			,default	 = True
		)

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_face_chain_parameters"): return layout

		layout.prop(params, "CR_face_chain_merge")
		layout.prop(params, "CR_face_chain_relink")

		return layout

class Rig(CloudFaceChainRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_face_chain")