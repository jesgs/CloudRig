import bpy
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, PointerProperty
from mathutils import Matrix

from ..utils.lattice import ensure_falloff_vgroup

from .cloud_base import Component_Base

class Component_Lattice(Component_Base):
	"""Create a simple lattice set-up. Lattice modifiers have to be added manually to the objects that should be deformed."""
	ui_name = "Lattice"
	relinking_behaviour = "Constraints will be moved to the Lattice Root."

	def initialize(self):
		super().initialize()
		self.create_deform_bone = False
		self.test_lattice_already_used()

	def create_bone_infos(self):
		super().create_bone_infos()
		self.lattice_root = self.make_lattice_root_ctrl(self.root_bone)
		self.hook_bone = self.make_hook_ctrl(self.lattice_root)

	def relink(self):
		"""Override cloud_base.
		Move constraints from the ORG to the Lattice Root bone and relink them.
		"""
		org = self.bones_org[0]
		for c in org.constraint_infos:
			self.lattice_root.constraint_infos.append(c)
			org.constraint_infos.remove(c)
			for d in c.drivers:
				self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
			c.relink()

	def make_lattice_root_ctrl(self, org_bi):
		name_parts = self.naming.slice_name(org_bi)
		root_name = self.naming.make_name(['ROOT', 'LTC'], name_parts[1], name_parts[2])
		root_bone = self.bone_sets['Lattice Controls'].new(
			name 						= root_name
			,source 					= org_bi
			,parent 					= org_bi
			,custom_shape 				= self.ensure_widget("Cube")
			,use_custom_shape_bone_size = True
		)
		return root_bone

	def make_hook_ctrl(self, root_bone):
		hook_name = root_bone.name.replace("ROOT-LTC", "LTC")
		hook_bone = self.bone_sets['Lattice Controls'].new(
			name 						= hook_name
			,source 					= root_bone
			,parent 					= root_bone
			,custom_shape 				= self.ensure_widget("Sphere")
			,use_custom_shape_bone_size = True
		)
		return hook_bone

	def finalize(self):
		super().finalize()
		root_pb = self.obj.pose.bones.get(self.root_bone.name)
		hook_pb = self.obj.pose.bones.get(self.hook_bone.name)
		lattice_ob = self.params.lattice.lattice
		if not lattice_ob or self.params.lattice.regenerate:
			self.meta_base_bone.rigify_parameters.CR_lattice_lattice = self.create_lattice(root_pb, hook_pb)
		elif lattice_ob:
			# Reset Hook inverse matrices
			for m in lattice_ob.modifiers:
				if m.type=='HOOK':
					m.subtarget = m.subtarget

	def create_lattice(self, root_bone: bpy.types.PoseBone, hook_bone: bpy.types.PoseBone):
		# If lattice doesn't exist, create it.
		lattice_ob = self.params.lattice.lattice
		lattice_exists = lattice_ob != None
		if not lattice_exists:
			lattice_name = hook_bone.name
			lattice = bpy.data.lattices.new(lattice_name)
			lattice_ob = bpy.data.objects.new(lattice_name, lattice)
			bpy.context.scene.collection.objects.link(lattice_ob)
		else:
			lattice_ob.modifiers.clear()
			lattice_ob.constraints.clear()

		resolution = 10
		# Set resolution
		lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = 1, 1, 1
		lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = [resolution]*3

		# Create a falloff vertex group
		vg = ensure_falloff_vgroup(lattice_ob, vg_name="Hook", multiplier=1.5)

		# Parent lattice to the generated rig
		lattice_ob.parent = self.obj
		# Bone-parent lattice to root bone
		lattice_ob.parent_type = 'BONE'
		lattice_ob.parent_bone = self.lattice_root.name
		lattice_ob.matrix_world = root_bone.matrix
		lattice_ob.matrix_world = lattice_ob.matrix_world @ Matrix.Scale(root_bone.length, 4)
		# Leave a custom property for the Generator, so it doesn't reset the
		# lattice's matrix to what it was before generation.
		lattice_ob['matrix_world'] = lattice_ob.matrix_world

		self.lock_transforms(lattice_ob)

		# Add Hook modifier to the lattice
		hook_mod = lattice_ob.modifiers.new(name="Hook", type='HOOK')
		hook_mod.object = self.obj
		hook_mod.vertex_group = vg.name
		hook_mod.subtarget = hook_bone.name

		return lattice_ob

	def test_lattice_already_used(self) -> bool:
		"""Test if the target lattice object is already being used by
		another cloud_lattice rig."""

		for rig in self.generator.rig_list:
			if isinstance(rig, type(self)):
				if rig == self:
					return
				if rig.params.CR_lattice_lattice == self.params.lattice.lattice and self.params.lattice.lattice != None:
					self.raise_metarig_error("Lattice shared by multiple components",
						operator = 'object.cloudrig_clear_pointer_param',
						op_kwargs = {'bone_name': self.meta_base_bone.name, 'param_name': 'CR_lattice_lattice'}
					)

	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Lattice Controls', preset=3, default_layers=[cls.DEFAULT_LAYERS.FK_MAIN])

	@classmethod
	def is_bone_set_used(cls, rig, params, set_name):
		if set_name == 'deform_bones':
			return False
		return super().is_bone_set_used(rig, params, set_name)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		cls.draw_prop(context, layout, params, "CR_lattice_lattice")
		cls.draw_prop(context, layout, params, "CR_lattice_regenerate")


class Params(PropertyGroup):
	lattice: PointerProperty(
		type		 = bpy.types.Object
		,name		 = "Lattice"
		,description = "Lattice Object that will be hooked up to this control. If not left empty, the already existing lattice will not be affected in any way, unless Regenerate Lattice is enabled"
	)
	regenerate: BoolProperty(
		name		 = "Regenerate"
		,description = "Whether to re-generate the lattice object on rig generation. Disable if you intend to modify the generated lattice object manually"
		,default	 = True
	)

class RigComponent(Component_Lattice):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)
