from bpy.types import PropertyGroup
from bpy.props import BoolProperty, StringProperty
from mathutils import Vector

from ..rig_component_features.bone_set import BoneInfo, BoneSet

from .cloud_base import Component_Base

class Component_CopyBone(Component_Base):
	"""Copy this bone to the generated rig."""
	ui_name = "Copy Bone"
	always_use_custom_props = True

	forced_params = {
		'custom_props.props_storage' : 'CUSTOM'
		,'custom_props.props_storage_bone' : ""
	}

	def initialize(self):
		super().initialize()

		self.orgless_name = self.base_bone.replace("ORG-", "")
		self.params.custom_props.props_storage_bone = self.orgless_name

		# If the metarig bone has a Child Of or Armature constraint, don't do any parenting logic.
		self.do_parenting = True
		for c in self.meta_base_bone.constraints:
			if c.type in ('CHILD_OF', 'ARMATURE'):
				self.do_parenting = False

	def create_bone_infos(self):
		super().create_bone_infos()
		bi = self.bones_org[0]

		# Strip ORG from bone's name (@name.setter takes care of everything)
		bi.name = self.orgless_name

		if not bi.use_custom_shape_bone_size:
			bi.custom_shape_scale /= bi.bbone_width * 10 * self.scale

		meta_bone = self.meta_bone(self.orgless_name)
		bi.layers = meta_bone.bone.layers[:]
		bi.use_deform = False
		if not meta_bone:
			self.add_log_bug("Bone not found in MetaRig", trouble_bone=self.orgless_name)
			return

		if meta_bone.custom_shape:
			self.add_to_widget_collection(meta_bone.custom_shape)

		if bi.rotation_mode == 'QUATERNION':
			self.add_log("Quaternion rotation"
				,trouble_bone = self.base_bone
				,description = f'"{meta_bone.name}" is on Quaternion rotation mode. Animator-facing controls should be set to Euler!'
				,icon = 'GIZMO'
				,operator = 'pose.cloudrig_troubleshoot_rotationmode'
				,op_kwargs = {'bone_name' : self.orgless_name}
				,op_text = f"Set {meta_bone.name} to Euler"
			)
			bi.rotation_mode = 'XYZ'

		if self.params.copy.create_deform:
			# Make a copy with DEF- prefix, as our deform bone.
			def_bone = self.make_def_bone(bi, self.bones_def)
			def_bone.parent = bi

		# In order for the bone group to transfer to the generated rig, we need to add a bone set to the generator.
		# Alternatively, this could be moved to a later generation stage so we don't have to rely on BoneInfo.
		meta_bg = meta_bone.bone_group
		if meta_bg:
			bg_name = meta_bg.name

			my_bone_set = BoneSet(self,
				ui_name = bg_name
				,bone_group = bg_name
				,layers = meta_bone.bone.layers[:]
				,normal = meta_bg.colors.normal[:]
				,active = meta_bg.colors.active[:]
				,select = meta_bg.colors.select[:]
				,defaults = self.defaults
			)
			my_bone_set.color_set = meta_bg.color_set
			bi.bone_group = bg_name
		else:
			my_bone_set = BoneSet(self,
				ui_name = 'Default'
				,bone_group = 'Default'
				,layers = meta_bone.bone.layers[:]
				,defaults = self.defaults
			)
		self.generator.bone_sets.append(my_bone_set)

		if self.params.copy.property_ui_subpanel:
			self.add_ui_data_of_bone(bi
				,self.params.copy.property_ui_subpanel
				,self.params.copy.property_ui_label
			)

		self.root_bone = bi
		if self.params.copy.custom_pivot:
			self.root_bone = self.create_custom_pivot(bi, my_bone_set)

		if self.params.copy.ensure_free:
			constrained_parent = self.create_parent_bone(self.root_bone # If custom pivot enabled, this should own that...
				,bone_set = self.bone_sets['Mechanism Bones']
			)
			constrained_parent.name = "CON-" + self.orgless_name
			for con_info in bi.constraint_infos[:]:
				if 'KEEP' not in con_info['name']:
					constrained_parent.constraint_infos.append(con_info) # ...but we always take the constraints from the bone, not from the custom pivot!
					bi.constraint_infos.remove(con_info)
			self.root_bone = constrained_parent

	def finalize(self):
		bi = self.bones_org[0]
		pb = self.obj.pose.bones.get(bi.name)
		pb.name = "ORG-"+self.orgless_name
		pb.name = self.orgless_name

	def create_custom_pivot(self, boneinfo, bone_set=None):
		if not bone_set:
			bone_set = boneinfo.bone_set
		pivot = self.create_parent_bone(boneinfo, bone_set)
		pivot.name = pivot.name.replace("P-", "PVT-")
		boneinfo.add_constraint('COPY_LOCATION', subtarget=pivot, invert_xyz = [True, True, True])
		pivot.custom_shape = self.ensure_widget('Axes_6')
		pivot.custom_shape_scale_xyz = Vector([max(boneinfo.custom_shape_scale_xyz)] * 3)
		pivot.custom_shape_translation = (0, 0, 0)
		pivot.custom_shape_rotation_euler = (0, 0, 0)
		pivot.layers = boneinfo.layers[:]
		pivot.bone_group = boneinfo.bone_group
		return pivot

	def add_ui_data_of_bone(self, bone: BoneInfo, panel_name: str, label_name=""):
		"""Add the UI data of a single BoneInfo's custom props to the rig's UI data.
		Properties of the bone will be displayed under the provided sub-panel and label.
		This will be displayed in the Sidebar->CloudRig->Settings.
		"""
		for prop_name, prop in bone.custom_props.items():
			prop_value = prop['default']

			# For the row names, we want each property to have its own row,
			# but matching properties from opposite side bones should be in
			# the same row.
			base_name = self.naming.slice_name(bone.name)[1]
			row_name = base_name + "_" + prop_name

			entry_name = prop_name
			flipped_name = self.naming.flipped_name(bone)
			opposite_bone = self.generator.metarig.data.bones.get(flipped_name)
			if flipped_name != bone.name and opposite_bone:
				# We also want to make sure the "entry name" is unique.
				# (User should NOT add a side indicator to the property name!)
				entry_name = self.side_prefix + " " + prop_name

			info = {
				'prop_bone' : bone.name,
				'prop_id' : prop_name,
			}

			if "$"+prop_name in self.meta_base_bone:
				# Rigger can specify strings for integer properties with a
				# property whose name starts with $. This property is expected
				# to be a list of strings, where the first strings matches with the value 0.
				# Negative integers are not supported for this.
				info['texts'] = self.meta_base_bone["$"+prop_name]

			self.add_ui_data(panel_name, row_name
				,info = info
				,default = prop_value
				,entry_name = entry_name
				,label_name = label_name
			)

	##############################
	# Parameters

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		cls.draw_prop(layout, params.copy, 'custom_pivot')
		cls.draw_prop(layout, params.copy, 'create_deform')
		cls.draw_prop(layout, params.copy, 'ensure_free')

	@classmethod
	def draw_custom_prop_params(cls, layout, context, params):
		layout = super().draw_custom_prop_params(layout, context, params)
		layout.separator()

		cls.draw_prop(layout, params.copy, 'property_ui_subpanel')
		row = layout.row()
		row.enabled = bool(property_ui_subpanel)
		cls.draw_prop(row, params.copy, 'property_ui_label')
		return layout

	@classmethod
	def is_bone_set_used(cls, rig, params, set_name):
		if set_name == 'deform_bones':
			return params.copy.create_deform

		return super().is_bone_set_used(rig, params, set_name)

class Params(PropertyGroup):
	create_deform: BoolProperty(
		name		 = "Create Deform"
		,description = 'Create a deforming child bone for this bone, prefixed with "DEF-"'
		,default	 = False
	)
	custom_pivot: BoolProperty(
		name		 = "Create Custom Pivot"
		,description = "Create a parent bone whose local translation is not propagated to the main control, but its rotation and scale are"
		,default	 = False
	)
	ensure_free: BoolProperty(
		name		 = "Ensure Free Transformation"
		,description = 'Create a parent which will have all constraints that this bone would have, unless the constraint name starts with "KEEP"'
		,default	 = False
	)
	property_ui_subpanel: StringProperty(
		name		 = "UI Sub-panel"
		,description = "Choose which sub-panel the custom properties should be displayed in. If empty, the properties won't appear in the rig UI"
	)
	property_ui_label: StringProperty(
		name		 = "UI Label"
		,description = "Choose which label the custom properties should be displayed under. If empty, the properties will display at the top of the subpanel"
	)

class RigComponent(Component_CopyBone):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)