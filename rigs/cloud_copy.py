from bpy.props import BoolProperty, StringProperty
from ..rig_features.bone_set import BoneInfo, BoneSet

from .cloud_base import CloudBaseRig

class CloudCopyRig(CloudBaseRig):
	"""Copy this bone to the generated rig."""
	always_use_custom_props = True

	forced_params = {
		'CR_base_props_storage' : 'CUSTOM'
		,'CR_base_props_storage_bone' : ""
	}

	def initialize(self):
		super().initialize()

		self.orgless_name = self.base_bone.replace("ORG-", "")
		self.params.CR_base_props_storage_bone = self.orgless_name

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

		meta_bone = self.meta_bone(bi.name)
		bi.layers = meta_bone.bone.layers[:]
		bi.use_deform = False
		if not meta_bone:
			self.add_log_bug("Bone not found in MetaRig", trouble_bone=bi.name)
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

		if self.params.CR_copy_create_deform:
			# Make a copy with DEF- prefix, as our deform bone.
			def_bone = self.make_def_bone(bi, self.bones_def)
			def_bone.parent = bi

		# In order for the bone group to transfer to the generated rig, we need to add a bone set to the generator.
		# Alternatively, this could be moved to a later generation stage so we don't have to rely on BoneInfo.
		meta_bg = meta_bone.bone_group
		new_set = None
		if meta_bg:
			bg_name = meta_bg.name

			new_set = BoneSet(self,
				ui_name = bg_name
				,bone_group = bg_name
				,layers = meta_bone.bone.layers[:]
				,normal = meta_bg.colors.normal[:]
				,active = meta_bg.colors.active[:]
				,select = meta_bg.colors.select[:]
				,defaults = self.defaults
			)
			new_set.color_set = meta_bg.color_set
			self.generator.bone_sets.append(new_set)
			bi.bone_group = bg_name

		if self.params.CR_copy_custom_pivot:
			self.root_bone = self.create_custom_pivot(bi, new_set)

		if self.params.CR_copy_property_ui_subpanel:
			self.add_ui_data_of_bone(bi
				,self.params.CR_copy_property_ui_subpanel
				,self.params.CR_copy_property_ui_label
			)

	def create_custom_pivot(self, boneinfo, bone_set=None):
		if not bone_set:
			bone_set = boneinfo.bone_set
		pivot = self.create_parent_bone(boneinfo, bone_set)
		pivot.name = pivot.name.replace("P-", "PVT-")
		boneinfo.add_constraint('COPY_LOCATION', subtarget=pivot, invert_xyz = [True, True, True])
		pivot.custom_shape = self.ensure_widget('Axes_6')
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
	def add_parameters(cls, params):
		"""Add rig parameters to the RigifyParameters PropertyGroup."""
		super().add_parameters(params)

		params.CR_copy_create_deform = BoolProperty(
			name		 = "Create Deform"
			,description = 'Create a deforming child bone for this bone, prefixed with "DEF-"'
			,default	 = False
		)
		params.CR_copy_custom_pivot = BoolProperty(
			name		 = "Create Custom Pivot"
			,description = "Create a parent bone whose local translation is not propagated to the main control, but its rotation and scale are"
			,default	 = False
		)
		params.CR_copy_property_ui_subpanel = StringProperty(
			name		 = "UI Sub-panel"
			,description = "Choose which sub-panel the custom properties should be displayed in. If empty, the properties won't appear in the rig UI"
		)
		params.CR_copy_property_ui_label = StringProperty(
			name		 = "UI Label"
			,description = "Choose which label the custom properties should be displayed under. If empty, the properties will display at the top of the subpanel"
		)

	@classmethod
	def draw_control_params(cls, layout, context, params):
		"""Create the ui for the rig parameters."""
		cls.draw_prop(layout, params, 'CR_copy_custom_pivot')
		cls.draw_prop(layout, params, 'CR_copy_create_deform')

	@classmethod
	def draw_custom_prop_params(cls, layout, context, params):
		layout = super().draw_custom_prop_params(layout, context, params)
		layout.separator()

		cls.draw_prop(layout, params, 'CR_copy_property_ui_subpanel')
		cls.draw_prop(layout, params, 'CR_copy_property_ui_label')
		return layout

	@classmethod
	def is_bone_set_used(cls, params, set_info):
		if set_info['name'] == 'Deform Bones':
			return params.CR_copy_create_deform

		return super().is_bone_set_used(params, set_info)

class Rig(CloudCopyRig):
	pass

from ..load_metarig import load_sample_by_file

def create_sample(obj):
	load_sample_by_file(__file__)