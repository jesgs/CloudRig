import bpy
from bpy.props import BoolProperty, IntProperty, FloatProperty

from .cloud_curve import CloudCurveRig

"""TODO:
"Subdivide Bones" param should be re-implemented as "number of bones", since it has to max out at 255 anyways. And the bones should be distributed evenly anyways. It just makes a lot more sense.

"""

class CloudSplineIKRig(CloudCurveRig):
	"""Create a bezier curve object to drive a bone chain with Spline IK constraint, controlled by Hooks."""

	forced_params = {
		'CR_curve_target' : None
	}

	def initialize_curve_rig(self):
		length = len(self.bones.org.main)
		subdiv = self.params.CR_spline_ik_subdivide
		total = length * subdiv
		assert total <= 255, f"Error: Spline IK rig on {self.base_bone}: Trying to subdivide each bone {subdiv} times, in a bone chain of {length}, would result in {total} bones. The Spline IK constraint only supports a chain of 255 bones. You should lower the subdivision level"

		self.num_controls = len(self.bones.org.main)+1 if self.params.CR_spline_ik_match_hooks else self.params.CR_spline_ik_hooks

	def ensure_bone_sets(self):
		super().ensure_bone_sets()
		self.def_chain = self.ensure_bone_set("Curve Deform Bones")

	def prepare_bones(self):
		super().prepare_bones()
		self.make_curve_root_ctrl()
		self.create_curve()
		self.make_ctrls_for_curve_points()
		self.make_def_chain()
		self.add_spline_ik()

	def make_curve_controls(self):
		""" Overrides.
			This rig's create_curve() relies on CloudBaseRig.prepare_bones() 
			having already run. But if we simply call super().prepare_bones(), 
			it will run make_ctrls_for_curve_points(), which, for this class, 
			relies on create_curve() running beforehand.
			So, we override this with nothing, and we put the calls in the
			correct order in our own prepare_bones().
		"""
		pass

	def create_curve(self):
		"""Find or create the Bezier Curve that will be used by the rig."""

		curve_ob = self.params.CR_curve_target
		if curve_ob:
			# There is no good way in the python API to delete curve points, so deleting the entire curve is necessary to allow us to generate with fewer controls than a previous generation.
			bpy.data.objects.remove(curve_ob)	# What's not so cool about this is that if anything in the scene was referencing this curve, that reference gets broken.


		sum_bone_length = sum([b.length for b in self.org_chain])
		length_unit = sum_bone_length / (self.num_controls-1)
		handle_length = length_unit * self.params.CR_spline_ik_handle_length

		# Create and name curve object.
		curve_name = "CUR-" + self.generator.metarig.name.replace("META-", "")
		curve_name += "_" + (self.params.CR_curve_hook_name if self.params.CR_curve_hook_name!="" else self.base_bone.replace("ORG-", ""))

		bpy.ops.curve.primitive_bezier_curve_add(radius=0.2, location=(0, 0, 0))

		curve_ob = bpy.context.view_layer.objects.active
		curve_ob.name = curve_name
		self.lock_transforms(curve_ob)

		self.meta_base_bone.rigify_parameters.CR_curve_target = self.params.CR_curve_target = curve_ob

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
			index = i if self.params.CR_spline_ik_match_hooks else -1
			loc, direction = self.vector_along_bone_chain(self.org_chain, point_along_chain, index)
			p.co = loc
			p.handle_right = loc + handle_length * direction
			p.handle_left  = loc - handle_length * direction

		# Reset selection so Rigify can continue execution.
		bpy.context.view_layer.objects.active = self.obj
		self.obj.select_set(True)
		bpy.ops.object.mode_set(mode='EDIT')

		return curve_ob

	def make_def_chain(self):
		segments = self.params.CR_spline_ik_subdivide

		count_def_bone = 0
		for org_bone in self.org_chain:
			for i in range(0, segments):
				## Create Deform bones
				def_name = self.params.CR_curve_hook_name if self.params.CR_curve_hook_name!="" else self.base_bone.replace("ORG-", "")
				def_name = "DEF-" + def_name + "_" + str(count_def_bone).zfill(3)
				count_def_bone += 1

				unit = org_bone.vector / segments
				def_bone = self.def_chain.new(
					name		 = def_name
					,source		 = org_bone
					,head		 = org_bone.head + (unit * i)
					,tail		 = org_bone.head + (unit * (i+1))
					,roll		 = org_bone.roll
					,bbone_width = 0.03
					,hide_select = self.mch_disable_select
					,use_deform	 = True
				)

				if len(self.def_chain) > 1:
					def_bone.parent = self.def_chain[-2]
				else:
					def_bone.parent = self.org_chain[0]

	def add_spline_ik(self):
		# Add constraint to deform chain
		self.def_chain[-1].add_constraint('SPLINE_IK'
			,target			  = self.params.CR_curve_target
			,use_curve_radius = True
			,chain_count	  = len(self.def_chain)
		)

	##############################
	# Parameters

	@classmethod
	def define_bone_sets(cls, params):
		super().define_bone_sets(params)
		"""Create parameters for this rig's bone sets."""
		cls.define_bone_set(params, "Curve Deform Bones", default_layers=[cls.default_layers('DEF')], override='DEF')

	@classmethod
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_spline_ik_show_settings = BoolProperty(name="Spline IK Settings")
		params.CR_spline_ik_match_hooks = BoolProperty(
			 name		 = "Match Controls to Bones"
			,description = "Hook controls will be created at each bone, instead of being equally distributed across the length of the chain"
			,default	 = True
		)
		params.CR_spline_ik_handle_length = FloatProperty(
			 name		 = "Curve Handle Length"
			,description = "Increasing this will result in longer curve handles, resulting in a sharper curve. A value of 1 means the curve handle reaches the neighbouring curve point"
			,default	 = 0.4
			,min		 = 0.01
			,max		 = 2.0
		)
		params.CR_spline_ik_hooks = IntProperty(
			 name		 = "Number of Hooks"
			,description = "Number of controls that will be spaced out evenly across the entire chain"
			,default	 = 3
			,min		 = 3
			,max		 = 99
		)
		params.CR_spline_ik_subdivide = IntProperty(
			 name="Subdivide Bones"
			,description="For each original bone, create this many deform bones in the spline chain (Bendy Bones do not work well with Spline IK, so we create real bones) NOTE: Spline IK only supports 255 bones in the chain"
			,default=3
			,min=1
			,max=99
		)

	@classmethod
	def curve_selector_ui(cls, layout, params):
		"""Overrides."""
		if not cls.draw_dropdown_menu(layout, params, "CR_curve_show_settings"):
			return layout

		cls.draw_prop(layout, params, "CR_curve_target", icon='OUTLINER_OB_CURVE')

	@classmethod
	def draw_cloud_params(cls, layout, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, params)

		if not cls.draw_dropdown_menu(layout, params, "CR_spline_ik_show_settings"):
			return layout

		cls.draw_prop(layout, params, "CR_spline_ik_subdivide")
		cls.draw_prop(layout, params, "CR_spline_ik_handle_length")

		# TODO: When this is false, the directions of the curve points and bones
		# don't match, and both of them are unsatisfactory. It would be nice if
		# we would interpolate between the direction of the two bones, using 
		# length_remaining/bone.length as a factor, or something similar to that.
		cls.draw_prop(layout, params, "CR_spline_ik_match_hooks")
		if not params.CR_spline_ik_match_hooks:
			cls.draw_prop(layout, params, "CR_spline_ik_hooks")

		return layout

class Rig(CloudSplineIKRig):
	pass

from ..load_metarig import load_sample

def create_sample(obj):
	load_sample("cloud_spline_ik")