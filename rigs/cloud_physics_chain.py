import bpy, bmesh

from typing import List
from ..bone import BoneInfo

from mathutils import Matrix
from math import sqrt

from bpy.props import BoolProperty, PointerProperty, EnumProperty, FloatProperty
from .cloud_fk_chain import CloudFKChainRig

class CloudPhysicsChainRig(CloudFKChainRig):
	"""FK Chain with cloth physics."""

	forced_params = {
		'CR_fk_chain_double_first' : False
		,'CR_fk_chain_hinge' : False

		,'CR_fk_chain_use_category_name' : False
		,'CR_fk_chain_category_name' : ""
		,'CR_fk_chain_use_limb_name' : False
		,'CR_fk_chain_limb_name' : ""
	}

	def initialize(self):
		super().initialize()

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.physics_chain = self.ensure_bone_set("Physics Bones")

	def prepare_bones(self):
		super().prepare_bones()

		phys_ob = self.ensure_cloth_object(self.fk_chain)
		if self.params.CR_physics_chain_make_ctrl:
			self.make_physics_chain(phys_ob, self.fk_chain)
		self.constrain_chain_to_phys_ob(phys_ob, self.fk_chain)

	def ensure_cloth_object(self, bone_chain: List[BoneInfo]):
		cloth_ob = self.params.CR_physics_chain_object
		if cloth_ob and not self.params.CR_physics_chain_force_regen:
			return cloth_ob

		cloth_mesh = bpy.data.meshes.new(name=self.phys_name(self.base_bone) )
		if not cloth_ob:
			# Create physics object.
			cloth_ob = bpy.data.objects.new(cloth_mesh.name, cloth_mesh)
			bpy.context.scene.collection.objects.link(cloth_ob)
		else:
			cloth_ob.data = cloth_mesh

		# Wipe modifiers & vertex groups
		cloth_ob.modifiers.clear()
		cloth_ob.vertex_groups.clear()

		# Create verts and edges using bmesh.
		bm = bmesh.new()
		bm.from_mesh(cloth_mesh)
		for i, bone in enumerate(bone_chain):
			vert = bm.verts.new(bone.head)
			bm.verts.ensure_lookup_table()
			if i > 0:
				bm.edges.new((bm.verts[i], bm.verts[i-1]))
			if i == len(bone_chain)-1:
				tail_vert = bm.verts.new(bone.tail)
				bm.edges.new((vert, tail_vert))

		bm.to_mesh(cloth_mesh)
		bm.free()


		### Create and assign vertex groups.

		# Total length of the chain
		total_length = 0
		for b in bone_chain:
			total_length += b.length
		total_length *= self.params.CR_physics_chain_pin_falloff_offset
		cum_length = 0

		pin_name = "PIN-"+cloth_ob.name

		# Assign weights.
		pin_vg = cloth_ob.vertex_groups.new(name=pin_name)
		pin_vg.add([0], 1, 'REPLACE')
		for i, v in enumerate(cloth_mesh.vertices):
			if i==0: continue
			pin_weight = 1
			name = self.phys_name(bone_chain[i-1])
			# Determine pin weight on this vertex.
			cum_length += bone_chain[i-1].length
			ratio = self.params.CR_physics_chain_pin_falloff_offset - cum_length / total_length
			if self.params.CR_physics_chain_pin_falloff == 'NONE':
				pin_weight = 0
			elif self.params.CR_physics_chain_pin_falloff == 'LINEAR':
				pin_weight = ratio
			elif self.params.CR_physics_chain_pin_falloff == 'QUADRATIC':
				pin_weight = ratio*ratio
			elif self.params.CR_physics_chain_pin_falloff == 'SQRT':
				pin_weight = sqrt(ratio)
			
			print("pin weight: " + str(pin_weight))

			vg = cloth_ob.vertex_groups.new(name=name)
			vg.add([i], 1, 'REPLACE')
			pin_vg.add([i], pin_weight, 'REPLACE')

		# Create Cloth modifier.
		cloth_mod = cloth_ob.modifiers.new(type='CLOTH', name="Cloth")
		cloth_mod.settings.vertex_group_mass = pin_name

		bpy.ops.object.mode_set(mode='OBJECT')
		bpy.context.view_layer.objects.active = cloth_ob
		cloth_ob.select_set(True)
		bpy.ops.object.mode_set(mode='EDIT')
		bpy.context.tool_settings.mesh_select_mode[0] = True
		bpy.ops.mesh.select_all(action='SELECT')
		# bpy.ops.mesh.extrude_region()
		bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value":(0, 0.01, 0)})
		bpy.ops.object.mode_set(mode='OBJECT')

		bpy.context.view_layer.objects.active = self.obj
		bpy.ops.object.mode_set(mode='EDIT')
		self.params.CR_physics_chain_object = cloth_ob
		self.meta_base_bone.rigify_parameters.CR_physics_chain_object = cloth_ob
		return cloth_ob

	def phys_name(self, thing):
		return "PSX-" + self.naming.strip_org(thing)

	def make_physics_chain(self, phys_ob, from_chain):
		# Make a chain of bones to control the physics object.
		next_parent = from_chain[0].parent
		if not next_parent:
			next_parent = self.root_bone
		for fk_ctrl in from_chain:
			phys_ctrl = self.new_bonei(self.physics_chain
				,name = self.phys_name(fk_ctrl)
				,source = fk_ctrl
				,custom_shape = fk_ctrl.custom_shape
				,custom_shape_scale = fk_ctrl.custom_shape_scale * 1.2
				,parent = next_parent
				,use_deform = True
			)
			next_parent = phys_ctrl
		
		pin_bone = self.new_bonei(self.physics_chain
			,name = "PIN-"+self.params.CR_physics_chain_object.name
			,source = self.physics_chain[0]
			,parent = self.physics_chain[0]
			,use_deform = True
		)
		self.set_layers(pin_bone, [type(self).default_layers('MCH')])

		# Add Armature modifier on physics object.
		if phys_ob.modifiers.find('Armature') == -1:
			arm_mod = phys_ob.modifiers.new(type='ARMATURE', name="Armature")
			arm_mod.object = self.obj

		# Parent first FK control to first PSX control.
		self.fk_chain[0].parent = self.physics_chain[0]

	def constrain_chain_to_phys_ob(self, phys_ob: bpy.types.Object, bone_chain: List[BoneInfo]):
		# For the moment, let's just slap some constraints on the FK chain.
		for fk_ctrl in self.fk_chain:
			fk_ctrl.add_constraint('DAMPED_TRACK'
				,use_preferred_defaults = False
				,target = phys_ob
				,subtarget = self.phys_name(fk_ctrl)
			)

	def finalize(self):
		cloth_ob = self.params.CR_physics_chain_object
		
		if self.params.CR_physics_chain_make_ctrl:
			# Move armature modifier to top of the stack
			bpy.context.view_layer.objects.active = cloth_ob
			bpy.ops.object.modifier_move_to_index(modifier='Armature', index=0)
			bpy.context.view_layer.objects.active = self.obj
			cloth_ob.parent = None
		else:
			# Parent cloth object.
			cloth_ob.parent = self.obj
			cloth_ob.parent_type = 'BONE'
			parent = self.org_chain[0].parent
			if not parent:
				parent = self.root_bone
			cloth_ob.parent_bone = parent.name

			cloth_ob.matrix_parent_inverse = cloth_ob.matrix_world.inverted()
			cloth_ob.matrix_world = Matrix.Identity((4))

	##############################
	# Parameters
	@classmethod
	def define_bone_sets(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().define_bone_sets(params)
		cls.define_bone_set(params, "Physics Bones", preset=3,	default_layers=[28])

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_physics_chain_show_settings = BoolProperty(
			name		 = "Physics Settings"
			,description = "Reveal settings for the cloud_physics_chain rig type"
		)
		params.CR_physics_chain_object = PointerProperty(
			type		 = bpy.types.Object
			,name		 = "Cloth Object"
			,description = "Select an object which has vertex groups corresponding to the bone names of the chain, prefixed with 'phys_'. Leave empty to generate the object"
		)
		params.CR_physics_chain_force_regen = BoolProperty(
			name		 = "Force Re-generate"
			,description = "Even if the mesh already exists, force it to be re-generated from scratch"
			,default	 = True
		)
		params.CR_physics_chain_pin_falloff = EnumProperty(
			name		 = "Pin Falloff"
			,description = "Type of falloff to apply to the generated cloth mesh's pin vertex group. The first vertex is always fully pinned"
			,items		 = [
				('NONE', "None", "First vertex fully pinned, rest fully unpinned"),
				('LINEAR', "Linear", "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated"),
				('QUADRATIC', "Loose", "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated and then raised to 2nd power"),
				('SQRT', "Stiff", "First vertex fully pinned, last vertex not pinned at all, vertices inbetween are linear interpolated and then their square root is taken"),

			]
			,default	 = 'QUADRATIC'
		)
		params.CR_physics_chain_pin_falloff_offset = FloatProperty(
			name		 = "Pin Falloff Offset"
			,description = "Calculate the pin falloffs as if the bone chain was this much longer than it actually is. Increasing this beyond 1.0 will cause all vertices to be more pinned"
			,default	 = 1.20
			,min		 = 0.0
			,max		 = 10.0
		)
		params.CR_physics_chain_make_ctrl = BoolProperty(
			name		 = "Make Control Chain"
			,description = "Create a control chain that can control the physics mesh using an Armature modifier"
			,default	 = True
		)

	@classmethod
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_physics_chain_show_settings"): return layout

		cls.draw_prop(layout, params, 'CR_physics_chain_object')
		if params.CR_physics_chain_object:
			cls.draw_prop(layout, params, 'CR_physics_chain_force_regen')
		
		if not params.CR_physics_chain_object or params.CR_physics_chain_force_regen:
			cls.draw_prop(layout, params, 'CR_physics_chain_pin_falloff')
			if params.CR_physics_chain_pin_falloff != 'NONE':
				cls.draw_prop(layout, params, 'CR_physics_chain_pin_falloff_offset')
		layout.separator()

		cls.draw_prop(layout, params, 'CR_physics_chain_make_ctrl')

		return layout

class Rig(CloudPhysicsChainRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_physics_chain")