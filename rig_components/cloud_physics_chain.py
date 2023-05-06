import bpy, bmesh
from bpy.types import PropertyGroup
from typing import List
from ..rig_component_features.bone import BoneInfo

from mathutils import Matrix
from math import sqrt

from bpy.props import BoolProperty, PointerProperty, EnumProperty, FloatProperty
from .cloud_fk_chain import Component_Chain_FK

class CloudPhysicsChainRig(Component_Chain_FK):
	"""FK Chain with cloth physics."""
	ui_name = "Chain: Physics"
	forced_params = {
		'fk_chain.double_first' : False
		,'fk_chain.hinge' : False
		,'fk_chain.position_along_bone' : 0
	}

	def initialize(self):
		super().initialize()

	def create_bone_infos(self):
		super().create_bone_infos()

		phys_ob = self.ensure_physics_object(self.bone_sets['FK Controls'])
		if self.params.physics_chain.make_ctrl:
			self.make_physics_chain(phys_ob, self.bone_sets['FK Controls'])
		self.constrain_chain_to_phys_ob(phys_ob, self.bone_sets['FK Controls'])

	def relink(self):
		"""Override cloud_fk_chain.
		Move constraints from ORG to PSX chain and relink them.
		"""
		for i, org in enumerate(self.bones_org):
			for c in org.constraint_infos[:]:
				if not c.is_from_real: continue
				to_bone = self.bone_sets['Physics Bones'][i]
				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	def ensure_physics_object(self, bone_chain: List[BoneInfo]):
		context = bpy.context

		phys_obj = self.params.physics_chain.phys_obj
		if phys_obj and not self.params.physics_chain.force_regen:
			return phys_obj

		cloth_mesh = bpy.data.meshes.new(name=self.phys_name(self.base_bone) )
		if not phys_obj:
			# Create physics object.
			phys_obj = bpy.data.objects.new(cloth_mesh.name, cloth_mesh)
			context.scene.collection.objects.link(phys_obj)
			phys_obj.parent = self.obj
		else:
			phys_obj.data = cloth_mesh

		# Wipe modifiers & vertex groups
		phys_obj.modifiers.clear()
		phys_obj.vertex_groups.clear()

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
		total_length *= self.params.physics_chain.pin_falloff_offset
		cum_length = 0

		pin_name = "PIN-"+phys_obj.name

		# Assign weights.
		pin_vg = phys_obj.vertex_groups.new(name=pin_name)
		pin_vg.add([0], 1, 'REPLACE')
		for i, v in enumerate(cloth_mesh.vertices):
			if i==0: continue
			pin_weight = 1
			name = self.phys_name(bone_chain[i-1])
			# Determine pin weight on this vertex.
			cum_length += bone_chain[i-1].length
			ratio = self.params.physics_chain.pin_falloff_offset - cum_length / total_length
			if self.params.physics_chain.pin_falloff == 'NONE':
				pin_weight = 0
			elif self.params.physics_chain.pin_falloff == 'LINEAR':
				pin_weight = ratio
			elif self.params.physics_chain.pin_falloff == 'QUADRATIC':
				pin_weight = ratio*ratio
			elif self.params.physics_chain.pin_falloff == 'SQRT':
				pin_weight = sqrt(ratio)

			vg = phys_obj.vertex_groups.new(name=name)
			vg.add([i], 1, 'REPLACE')
			pin_vg.add([i], pin_weight, 'REPLACE')

		# Create Cloth modifier.
		cloth_mod = phys_obj.modifiers.new(type='CLOTH', name="Cloth")
		cloth_mod.settings.vertex_group_mass = pin_name

		bpy.ops.object.mode_set(mode='OBJECT')
		context.view_layer.objects.active = phys_obj
		phys_obj.select_set(True)
		bpy.ops.object.mode_set(mode='EDIT')
		context.tool_settings.mesh_select_mode[0] = True
		bpy.ops.mesh.select_all(action='SELECT')
		# bpy.ops.mesh.extrude_region()
		bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value":(0, 0.01, 0)})
		bpy.ops.object.mode_set(mode='OBJECT')

		context.view_layer.objects.active = self.obj
		bpy.ops.object.mode_set(mode='EDIT')
		self.params.physics_chain.phys_obj = phys_obj
		self.meta_base_bone.rigify_parameters.CR_physics_chain_object = phys_obj
		return phys_obj

	def phys_name(self, thing):
		return "PSX-" + self.naming.strip_org(thing)

	def make_physics_chain(self, phys_ob, from_chain):
		# Make a chain of bones to control the physics object.
		next_parent = from_chain[0].parent
		for fk_ctrl in from_chain:
			phys_ctrl = self.bone_sets['Physics Bones'].new(
				name = self.phys_name(fk_ctrl)
				,source = fk_ctrl
				,custom_shape = fk_ctrl.custom_shape
				,custom_shape_scale = fk_ctrl.custom_shape_scale * 1.2
				,parent = next_parent
				,use_deform = True
			)
			next_parent = phys_ctrl

		pin_bone = self.bone_sets['Physics Bones'].new(
			name = "PIN-"+self.params.physics_chain.phys_obj.name
			,source = self.bone_sets['Physics Bones'][0]
			,parent = self.bone_sets['Physics Bones'][0]
			,use_deform = True
		)
		self.set_layers(pin_bone, [type(self).DEFAULT_LAYERS.MCH])

		# Add Armature modifier on physics object.
		if phys_ob.modifiers.find('Armature') == -1:
			arm_mod = phys_ob.modifiers.new(type='ARMATURE', name="Armature")
			arm_mod.object = self.obj

		# Parent first FK control to first PSX control.
		self.bone_sets['FK Controls'][0].parent = self.bone_sets['Physics Bones'][0]

		# Set first PSX control as the limb root bone, for correct parent switch
		# and root parenting behaviours
		self.limb_root_bone = self.bone_sets['Physics Bones'][0]

	def constrain_chain_to_phys_ob(self, phys_ob: bpy.types.Object, bone_chain: List[BoneInfo]):
		# For the moment, let's just slap some constraints on the FK chain.
		for fk_ctrl in self.bone_sets['FK Controls']:
			fk_ctrl.add_constraint('DAMPED_TRACK'
				,use_preferred_defaults = False
				,target = phys_ob
				,subtarget = self.phys_name(fk_ctrl)
			)

	def finalize(self):
		phys_obj = self.params.physics_chain.phys_obj
		context = bpy.context

		if self.params.physics_chain.make_ctrl:
			# Move armature modifier to top of the stack
			context.view_layer.objects.active = phys_obj
			bpy.ops.object.modifier_move_to_index(modifier='Armature', index=0)
			context.view_layer.objects.active = self.obj
			phys_obj.parent = None
		else:
			# Parent physics object.
			phys_obj.parent = self.obj
			phys_obj.parent_type = 'BONE'
			parent = self.bones_org[0].parent
			if not parent:
				parent = self.root_bone
			phys_obj.parent_bone = parent.name

			phys_obj.matrix_parent_inverse = phys_obj.matrix_world.inverted()
			phys_obj.matrix_world = Matrix.Identity((4))

	##############################
	# Parameters
	@classmethod
	def add_bone_set_parameters(cls, params):
		"""Create parameters for this rig's bone sets."""
		super().add_bone_set_parameters(params)
		cls.define_bone_set(params, 'Physics Bones', preset=3,	default_layers=[28])

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		super().draw_control_params(layout, context, params)

		layout.separator()
		cls.draw_control_label(layout, "Physics")

		cls.draw_prop(layout, params.physics_chain, 'phys_obj')
		cls.draw_prop(layout, params.physics_chain, 'force_regen')

		if not params.physics_chain.phys_obj or params.physics_chain.force_regen:
			cls.draw_prop(layout, params.physics_chain, 'pin_falloff')
			if params.physics_chain.pin_falloff != 'NONE':
				cls.draw_prop(layout, params.physics_chain, 'pin_falloff_offset')

		cls.draw_prop(layout, params.physics_chain, 'make_ctrl')


class Params(PropertyGroup):
	phys_obj: PointerProperty(
		type		 = bpy.types.Object
		,name		 = "Cloth Object"
		,description = "Select an object which has vertex groups corresponding to the bone names of the chain, prefixed with 'phys_'. Leave empty to generate the object"
	)
	force_regen: BoolProperty(
		name		 = "Force Re-generate"
		,description = "Even if the mesh already exists, force it to be re-generated from scratch"
		,default	 = True
	)
	pin_falloff: EnumProperty(
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
	pin_falloff_offset: FloatProperty(
		name		 = "Pin Falloff Offset"
		,description = "Calculate the pin falloffs as if the bone chain was this much longer than it actually is. Increasing this beyond 1.0 will cause all vertices to be more pinned"
		,default	 = 1.20
		,min		 = 0.0
		,max		 = 10.0
	)
	make_ctrl: BoolProperty(
		name		 = "Create Physics Controls"
		,description = "Create a control chain that can control the physics mesh using an Armature modifier"
		,default	 = True
	)

class RigComponent(CloudPhysicsChainRig):
	pass

# For the rig type template to work, there must be an object in CloudRig/metarigs/MetaRigs.blend called Sample_cloud_template.
from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)