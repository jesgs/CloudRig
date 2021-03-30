import bpy
from bpy.props import BoolProperty, PointerProperty
from mathutils import Matrix

from ..bone import BoneInfo, BoneSet
from ..utils.lattice import ensure_falloff_vgroup

from .cloud_base import CloudBaseRig

# We generate a lattice object with a reasonable resolution, and a smooth falloff of
# weights using the utils we have in LatticeMagic addon.
# (need to bring over, into maybe a utils.lattice module)
	# Unless the lattice already existed.

# Create a root control for the lattice set-up.

# The lattice is object-parented to the generated rig.
	# Then an Armature constraint is added, targetting the root control.
	# Unless an armature constraint already existed, because the lattice already existed.

# We create a Hook control, and ensure a Hook modifier on the lattice object, with the generated vertex group, targetting this hook control.
	# Unless the lattice already existed.

class CloudLatticeRig(CloudBaseRig):
	"""Create a simple lattice set-up. Lattice modifiers have to be added manually to the objects that should be deformed."""

	def initialize(self):
		super().initialize()
		self.create_deform_bone = False

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.lattice_ctrls = self.ensure_bone_set("Lattice Controls")

	def create_bone_infos(self):
		super().create_bone_infos()
		org_bi = self.org_chain[0]

		self.root_bone = self.make_root_ctrl(org_bi)
		self.hook_bone = self.make_hook_ctrl(self.root_bone)

	def make_root_ctrl(self, org_bi):
		root_name = org_bi.name.replace("ORG", "ROOT-LTC")
		root_bone = self.lattice_ctrls.new(
			name 						= root_name
			,source 					= org_bi
			,parent 					= org_bi
			,custom_shape 				= self.ensure_widget("Cube")
			,use_custom_shape_bone_size = True
		)
		return root_bone

	def make_hook_ctrl(self, root_bone):
		hook_name = root_bone.name.replace("ROOT-LTC", "LTC")
		hook_bone = self.lattice_ctrls.new(
			name 						= hook_name
			,source 					= root_bone
			,parent 					= root_bone
			,custom_shape 				= self.ensure_widget("Sphere")
			,use_custom_shape_bone_size = True
		)
		return hook_bone

	def finalize(self):
		super().finalize()
		meta_pose_bone = self.generator.metarig.pose.bones.get(self.base_bone[4:])
		root_pb = self.obj.pose.bones.get(self.root_bone.name)
		hook_pb = self.obj.pose.bones.get(self.hook_bone.name)

		lattice_ob = self.params.CR_lattice_lattice
		if not lattice_ob or self.params.CR_lattice_regenerate:
			meta_pose_bone.rigify_parameters.CR_lattice_lattice = self.create_lattice(root_pb, hook_pb)
		elif lattice_ob:
			# Reset Hook inverse matrices
			for m in lattice_ob.modifiers:
				if m.type=='HOOK':
					m.subtarget = m.subtarget

	def create_lattice(self, root_bone: bpy.types.PoseBone, hook_bone: bpy.types.PoseBone):
		# If lattice doesn't exist, create it.
		lattice_ob = self.params.CR_lattice_lattice
		new_lattice = lattice_ob == None
		if new_lattice:
			lattice_name = root_bone.name.replace("ROOT", "LTC")
			lattice = bpy.data.lattices.new(lattice_name)
			lattice_ob = bpy.data.objects.new(lattice_name, lattice)
			bpy.context.scene.collection.objects.link(lattice_ob)
		else:
			lattice_ob.modifiers.clear()
			lattice_ob.constraints.clear()

		resolution = 10
		# Set resolution
		lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = 1, 1, 1
		lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = 2, 2, 2 # Bug workaround.
		lattice_ob.data.points_u, lattice_ob.data.points_v, lattice_ob.data.points_w = [resolution]*3

		# Create a falloff vertex group
		vg = ensure_falloff_vgroup(lattice_ob, vg_name="Hook", multiplier=1.5)

		# Parent lattice to the generated rig
		lattice_ob.parent = self.obj
		# Bone-parent lattice to root bone
		lattice_ob.parent_type = 'BONE'
		lattice_ob.parent_bone = root_bone.name
		lattice_ob.matrix_world = root_bone.matrix
		lattice_ob.matrix_world = lattice_ob.matrix_world @ Matrix.Scale(root_bone.length, 4)

		self.lock_transforms(lattice_ob)

		# Add Hook modifier to the lattice
		hook_mod = lattice_ob.modifiers.new(name="Hook", type='HOOK')
		hook_mod.object = self.obj
		hook_mod.vertex_group = vg.name
		hook_mod.subtarget = hook_bone.name

		return lattice_ob

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Lattice Controls", preset=3, default_layers=[cls.default_layers('FK_MAIN')])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup"""
		super().add_parameters(params)

		params.CR_lattice_show_settings = BoolProperty(
			name		 = "Lattice Settings"
			,description = "Reveal settings for the cloud_lattice rig type"
		)

		params.CR_lattice_lattice = PointerProperty(
			type		 = bpy.types.Object
			,name		 = "Lattice"
			,description = "Lattice Object that will be hooked up to this control. If not left empty, the already existing lattice will not be affected in any way, unless Regenerate Lattice is enabled"
		)
		params.CR_lattice_regenerate = BoolProperty(
			name		 = "Regenerate"
			,description = "Whether to re-generate the lattice object on rig generation. Disable if you intend to modify the generated lattice object manually"
			,default	 = True
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, 'CR_lattice_show_settings'): return layout

		cls.draw_prop(layout, params, "CR_lattice_lattice")
		cls.draw_prop(layout, params, "CR_lattice_regenerate")

		return layout

class Rig(CloudLatticeRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)