import bpy
from bpy.props import BoolProperty, IntProperty, FloatProperty

from .cloud_curve import CloudCurveRig

"""TODO:
"Subdivide Bones" param should be re-implemented as "number of bones", since it has to max out at 255 anyways. And the bones should be distributed evenly anyways. It just makes a lot more sense.

"""

class CloudSplineIKRig(CloudCurveRig):
	"""Create a bezier curve object to drive a bone chain with Spline IK constraint, controlled by Hooks."""

	relinking_behaviour = "Constraints will be moved to the Hook controls. Only works when Match Controls to Bones option is enabled."	# TODO: Gray this out otherwise!

	forced_params = {
		# 'CR_curve_target' : None TODO: This shouldn't be user-modifiable, but it also can't be set to None, because we need the curve reference in create_curve_object().
	}

	def initialize_curve_rig(self):
		length = len(self.bones.org.main)
		subdiv = self.params.CR_spline_ik_subdivide
		total = length * subdiv
		if length > 255:
			self.raise_error(f"Spline IK rig consists of {length} bones but the Spline IK constraint only supports a chain of 255 bones.")
		if total > 255:
			old_total = total
			old_subdiv = subdiv
			while total > 255:
				subdiv -= 1
				total = length * subdiv
			self.add_log("Spline IK longer than 255 bones"
				,description = f"Trying to subdivide {length} bones {old_subdiv} times, would result in {old_total} bones. \nThe Spline IK constraint only supports a chain of 255 bones, so subdivisions has been capped at {subdiv} for a new total of {total} bones."
			)

		self.num_controls = len(self.bones.org.main)+1 if self.params.CR_spline_ik_match_hooks else self.params.CR_spline_ik_hooks

	def create_bone_infos(self):
		super().create_bone_infos()
		self.make_curve_root_ctrl()
		self.create_curve_object()
		self.make_ctrls_for_curve_points()
		self.make_def_chain()
		self.add_spline_ik()

	def make_curve_controls(self):
		""" Overrides.
			This rig's create_curve_object() relies on CloudBaseRig.create_bone_infos()
			having already run. But if we simply call super().create_bone_infos(),
			it will run make_ctrls_for_curve_points(), which, for this class,
			relies on create_curve_object() running beforehand.
			So, we override this with nothing, and we put the calls in the
			correct order in our own create_bone_infos().
		"""
		# TODO: This could perhaps be better done with a callback of some kind.
		pass

	def create_curve_object(self):
		"""Find or create the Bezier Curve that will be used by the rig."""

		curve_ob = self.params.CR_curve_target

		curve_name = "CUR-" + self.generator.metarig.name.replace("META-", "")
		curve_name += "_" + (self.params.CR_curve_hook_name if self.params.CR_curve_hook_name!="" else self.base_bone.replace("ORG-", ""))

		if curve_ob:
			# Remove all splines, then add a new one.
			for spline in curve_ob.data.splines[:]:
				curve_ob.data.splines.remove(spline)
			spline = curve_ob.data.splines.new(type='BEZIER')
		else:
			# Create and name curve object.
			curve = bpy.data.curves.new(curve_name, 'CURVE')
			curve_ob = bpy.data.objects.new(curve_name, curve)
			bpy.context.scene.collection.objects.link(curve_ob)
			spline = curve.splines.new(type='BEZIER')
			self.lock_transforms(curve_ob)

		curve_ob.data.dimensions = '3D'
		sum_bone_length = sum([b.length for b in self.bone_sets['Original Bones']])
		length_unit = sum_bone_length / (self.num_controls-1)
		handle_length = length_unit * self.params.CR_spline_ik_handle_length

		self.meta_base_bone.rigify_parameters.CR_curve_target = self.params.CR_curve_target = curve_ob

		# Add the necessary number of curve points to the spline
		points = spline.bezier_points
		points.add( self.num_controls-len(points) )
		num_points = len(points)

		# Configure control points...
		for i in range(0, num_points):
			point_along_chain = i * length_unit
			p = points[i]

			# Place control points
			index = i if self.params.CR_spline_ik_match_hooks else -1
			loc, direction = self.vector_along_bone_chain(self.bone_sets['Original Bones'], point_along_chain, index)
			p.co = loc
			p.handle_right = loc + handle_length * direction
			p.handle_left  = loc - handle_length * direction

		return curve_ob

	def make_def_chain(self):
		segments = self.params.CR_spline_ik_subdivide

		count_def_bone = 0
		for org_bone in self.bone_sets['Original Bones']:
			for i in range(0, segments):
				## Create Deform bones
				def_name = self.params.CR_curve_hook_name if self.params.CR_curve_hook_name!="" else self.base_bone.replace("ORG-", "")
				def_name = "DEF-" + def_name + "_" + str(count_def_bone).zfill(3)
				count_def_bone += 1

				unit = org_bone.vector / segments
				def_bone = self.bone_sets['Curve Deform Bones'].new(
					name		 = def_name
					,source		 = org_bone
					,head		 = org_bone.head + (unit * i)
					,tail		 = org_bone.head + (unit * (i+1))
					,roll		 = org_bone.roll
					,bbone_width = 0.03
					,hide_select = self.mch_disable_select
					,use_deform	 = True
				)

				if len(self.bone_sets['Curve Deform Bones']) > 1:
					def_bone.parent = self.bone_sets['Curve Deform Bones'][-2]
				else:
					def_bone.parent = self.bone_sets['Original Bones'][0]

	def add_spline_ik(self):
		# Add constraint to deform chain
		self.bone_sets['Curve Deform Bones'][-1].add_constraint('SPLINE_IK'
			,target			  = self.params.CR_curve_target
			,use_curve_radius = True
			,chain_count	  = len(self.bone_sets['Curve Deform Bones'])
		)

	def relink(self):
		"""Override cloud_base.
		Move constraints from ORG to Hook controls and relink them.
		Only works when CR_spline_ik_match_hooks==True. TODO: Indicate this by graying out in the UI!
		"""
		if not self.params.CR_spline_ik_match_hooks: return
		for i, org in enumerate(self.bone_sets['Original Bones']):
			for c in org.constraint_infos[:]:
				if not c.is_from_real: continue
				to_bone = self.bone_sets['Curve Hooks'][i]
				to_bone.constraint_infos.append(c)
				org.constraint_infos.remove(c)
				for d in c.drivers:
					self.obj.driver_remove(f'pose.bones["{org.name}"].constraints["{c.name}"].{d["prop"]}')
				c.relink()

	def configure_bones(self):
		"""This is a rare case of using a Rigify stage, because we actually
		do want to apply the rest pose of the deform bones, as dictated by
		the Spline IK constraint."""
		super().configure_bones()
		bpy.ops.object.mode_set(mode='POSE')
		for pb in self.obj.pose.bones:
			pb.bone.select = False

		for def_bone in self.bone_sets['Curve Deform Bones']:
			pb = self.obj.pose.bones.get(def_bone.name)
			if not pb: continue
			pb.bone.select = True

		bpy.ops.pose.armature_apply(selected=True)
		bpy.ops.object.mode_set(mode='OBJECT')


	##############################
	# Parameters

	@classmethod
	def add_bone_set_parameters(cls, params):
		super().add_bone_set_parameters(params)
		"""Create parameters for this rig's bone sets."""
		cls.define_bone_set(params, 'Curve Deform Bones', default_layers=[cls.DEFAULT_LAYERS.DEF], is_advanced=True)

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
	def draw_cloud_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		layout = super().draw_cloud_params(layout, context, params)

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

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)