import bpy
from bpy.props import BoolProperty, IntProperty, FloatProperty

from .cloud_curve import CloudCurveRig

class CloudSplineIKRig(CloudCurveRig):
	"""Create a bezier curve object to drive a bone chain with Spline IK constraint, controlled by Hooks."""

	def initialize_curve_rig(self):
		length = len(self.bones.org.main)
		subdiv = self.params.CR_subdivide_deform
		total = length * subdiv
		assert total <= 255, f"Error: Spline IK rig on {self.base_bone}: Trying to subdivide each bone {subdiv} times, in a bone chain of {length}, would result in {total} bones. The Spline IK constraint only supports a chain of 255 bones. You should lower the subdivision level"

		self.num_controls = len(self.bones.org.main)+1 if self.params.CR_match_hooks_to_bones else self.params.CR_num_hooks

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.def_bones = self.ensure_bone_set("Curve Deform Bones")

	def create_curve(self):
		""" Find or create the Bezier Curve that will be used by the rig. """
		
		curve_ob = self.params.CR_target_curve
		if curve_ob:
			# There is no good way in the python API to delete curve points, so deleting the entire curve is necessary to allow us to generate with fewer controls than a previous generation.
			bpy.data.objects.remove(curve_ob)	# What's not so cool about this is that if anything in the scene was referencing this curve, that reference gets broken.

		
		sum_bone_length = sum([b.length for b in self.org_chain])
		length_unit = sum_bone_length / (self.num_controls-1)
		handle_length = length_unit * self.params.CR_curve_handle_length

		curve_name = "CUR-" + self.generator.metarig.name.replace("META-", "")
		curve_name += "_" + (self.params.CR_hook_name if self.params.CR_hook_name!="" else self.base_bone.replace("ORG-", ""))
		
		# Create and name curve object.
		bpy.ops.curve.primitive_bezier_curve_add(radius=0.2, location=(0, 0, 0))

		curve_ob = bpy.context.view_layer.objects.active
		curve_ob.name = curve_name
		self.meta_base_bone.rigify_parameters.CR_target_curve = self.params.CR_target_curve = curve_ob

		self.lock_transforms(curve_ob)

		# Place the first and last bezier points to the first and last bone.
		spline = curve_ob.data.splines[0]
		points = spline.bezier_points

		# Add the necessary number of curve points
		points.add( self.num_controls-len(points) )
		num_points = len(points)

		# Configure control points...
		for i in range(0, num_points):
			curve_ob = bpy.data.objects.get(curve_name)
			point_along_chain = i * length_unit
			spline = curve_ob.data.splines[0]
			points = spline.bezier_points
			p = points[i]

			# Place control points
			index = i if self.params.CR_match_hooks_to_bones else -1
			loc, direction = self.vector_along_bone_chain(self.org_chain, point_along_chain, index)
			p.co = loc
			p.handle_right = loc + handle_length * direction
			p.handle_left  = loc - handle_length * direction
		
		# Reset selection so Rigify can continue execution.
		bpy.context.view_layer.objects.active = self.obj
		self.obj.select_set(True)
		bpy.ops.object.mode_set(mode='EDIT')

		return curve_ob

	def create_def_chain(self):
		segments = self.params.CR_subdivide_deform

		count_def_bone = 0
		for org_bone in self.org_chain:
			for i in range(0, segments):
				## Create Deform bones
				def_name = self.params.CR_hook_name if self.params.CR_hook_name!="" else self.base_bone.replace("ORG-", "")
				def_name = "DEF-" + def_name + "_" + str(count_def_bone).zfill(3)
				count_def_bone += 1

				unit = org_bone.vector / segments
				def_bone = self.def_bones.new(
					name		 = def_name
					,source		 = org_bone
					,head		 = org_bone.head + (unit * i)
					,tail		 = org_bone.head + (unit * (i+1))
					,roll		 = org_bone.roll
					,bbone_width = 0.03
					,hide_select = self.mch_disable_select
					,use_deform	 = True
				)

				if len(self.def_bones) > 1:
					def_bone.parent = self.def_bones[-2]
				else:
					def_bone.parent = self.org_chain[0]

	def prepare_bones(self):
		super().prepare_bones()
		self.define_curve_root_ctrl()
		self.create_curve()
		self.define_ctrls_for_curve_points()
		self.create_def_chain()
		self.add_spline_ik()
	
	def define_curve_controls(self):
		# This rig's create_curve() relies on CloudBaseRig.prepare_bones() having already run.
		# But if we simply call super().prepare_bones(), it will run define_ctrls_for_curve_points(), which, for this class, relies on create_curve() running beforehand.
		pass

	def add_spline_ik(self):
		# Add constraint to deform chain
		self.def_bones[-1].add_constraint('SPLINE_IK'
			,target			  = self.params.CR_target_curve
			,use_curve_radius = True
			,chain_count	  = len(self.def_bones)
		)

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		super().define_bone_sets(params)
		""" Create parameters for this rig's bone sets. """
		cls.define_bone_set(params, "Curve Deform Bones", default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		""" Add the parameters of this rig type to the
			RigifyParameters PropertyGroup
		"""
		super().add_parameters(params)
		
		params.CR_show_spline_ik_settings = BoolProperty(name="Spline IK Rig")
		params.CR_match_hooks_to_bones = BoolProperty(
			 name		 = "Match Controls to Bones"
			,description = "Hook controls will be created at each bone, instead of being equally distributed across the length of the chain"
			,default	 = True
		)
		params.CR_curve_handle_length = FloatProperty(
			 name		 = "Curve Handle Length"
			,description = "Increasing this will result in longer curve handles, resulting in a sharper curve. A value of 1 means the curve handle reaches the neighbouring curve point"
			,default	 = 0.4
			,min		 = 0.01
			,max		 = 2.0
		)
		params.CR_num_hooks = IntProperty(
			 name		 = "Number of Hooks"
			,description = "Number of controls that will be spaced out evenly across the entire chain"
			,default	 = 3
			,min		 = 3
			,max		 = 99
		)
		params.CR_subdivide_deform = IntProperty(
			 name="Subdivide Bones"
			,description="For each original bone, create this many deform bones in the spline chain (Bendy Bones do not work well with Spline IK, so we create real bones) NOTE: Spline IK only supports 255 bones in the chain"
			,default=3
			,min=1
			,max=99
		)

	@classmethod
	def curve_selector_ui(cls, layout, params):
		if not cls.cloud_dropdown_ui(layout, params, "CR_show_curve_rig_settings"): return layout

		target_curve_row = layout.row()
		target_curve_row.prop(params, "CR_target_curve", icon='OUTLINER_OB_CURVE')
		target_curve_row.enabled = False

	@classmethod
	def cloud_params_ui(cls, layout, params):
		""" Create the ui for the rig parameters.
		"""
		layout = super().cloud_params_ui(layout, params)

		if not cls.cloud_dropdown_ui(layout, params, "CR_show_spline_ik_settings"): return layout

		layout.prop(params, "CR_subdivide_deform")
		layout.prop(params, "CR_curve_handle_length")

		layout.prop(params, "CR_match_hooks_to_bones")	# TODO: When this is false, the directions of the curve points and bones don't match, and both of them are unsatisfactory. It would be nice if we would interpolate between the direction of the two bones, using length_remaining/bone.length as a factor, or something similar to that.
		if not params.CR_match_hooks_to_bones:
			layout.prop(params, "CR_num_hooks")

		return layout

class Rig(CloudSplineIKRig):
	pass

def create_sample(obj):
    # generated by rigify.utils.write_metarig
    bpy.ops.object.mode_set(mode='EDIT')
    arm = obj.data

    bones = {}

    bone = arm.edit_bones.new('Cable_1')
    bone.head = 0.0000, 0.0000, 0.0000
    bone.tail = 0.0000, -0.5649, 0.0000
    bone.roll = -3.1416
    bone.use_connect = False
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0282
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bones['Cable_1'] = bone.name
    bone = arm.edit_bones.new('Cable_2')
    bone.head = 0.0000, -0.5649, 0.0000
    bone.tail = 0.0000, -1.1299, 0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0282
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Cable_1']]
    bones['Cable_2'] = bone.name
    bone = arm.edit_bones.new('Cable_3')
    bone.head = 0.0000, -1.1299, 0.0000
    bone.tail = 0.0000, -1.6948, -0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Cable_2']]
    bones['Cable_3'] = bone.name
    bone = arm.edit_bones.new('Cable_4')
    bone.head = 0.0000, -1.6948, -0.0000
    bone.tail = 0.0000, -2.2598, 0.0000
    bone.roll = -3.1416
    bone.use_connect = True
    bone.bbone_x = 0.0399
    bone.bbone_z = 0.0399
    bone.head_radius = 0.0565
    bone.tail_radius = 0.0565
    bone.envelope_distance = 0.1412
    bone.envelope_weight = 1.0000
    bone.use_envelope_multiply = 0.0000
    bone.parent = arm.edit_bones[bones['Cable_3']]
    bones['Cable_4'] = bone.name

    bpy.ops.object.mode_set(mode='OBJECT')
    pbone = obj.pose.bones[bones['Cable_1']]
    pbone.rigify_type = 'cloud_spline_ik'
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    try:
        pbone.rigify_parameters.CR_double_root = ""
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_subdivide_deform = 10
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_controls_for_handles = True
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_show_spline_ik_settings = True
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_show_display_settings = False
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_curve_handle_length = 2.5
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_rotatable_handles = False
    except AttributeError:
        pass
    try:
        pbone.rigify_parameters.CR_hook_name = "Cable"
    except AttributeError:
        pass
    pbone = obj.pose.bones[bones['Cable_2']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    pbone = obj.pose.bones[bones['Cable_3']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'
    pbone = obj.pose.bones[bones['Cable_4']]
    pbone.rigify_type = ''
    pbone.lock_location = (False, False, False)
    pbone.lock_rotation = (False, False, False)
    pbone.lock_rotation_w = False
    pbone.lock_scale = (False, False, False)
    pbone.rotation_mode = 'QUATERNION'

    bpy.ops.object.mode_set(mode='EDIT')
    for bone in arm.edit_bones:
        bone.select = False
        bone.select_head = False
        bone.select_tail = False
    for b in bones:
        bone = arm.edit_bones[bones[b]]
        bone.select = True
        bone.select_head = True
        bone.select_tail = True
        arm.edit_bones.active = bone

    return bones
