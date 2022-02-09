import bpy
from .utils.misc import find_rig_class

def get_active_pose_bone(context):
	"""Return the PoseBone of the active bone. Can be None."""
	posebone = context.active_pose_bone
	if not posebone:
		bone = context.active_bone
		posebone = context.object.pose.bones.get(bone.name)
	return posebone

class CloudParamSubPanel(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_parent_id = "BONE_PT_rigify_buttons"
	bl_options = {'DEFAULT_CLOSED'}

	draw_function_name = "draw_parenting_params"
	advanced_only = False

	@classmethod
	def poll(cls, context):
		pb = get_active_pose_bone(context)
		if not pb:
			return False
		rig_class = find_rig_class(pb.rigify_type)
		if not rig_class:
			return False
		if not hasattr(rig_class, cls.draw_function_name):
			return False
		if cls.advanced_only and not rig_class.is_advanced_mode(context):
			return False
		return True

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		layout.use_property_decorate = False
		layout = layout.column()

		pb = context.active_pose_bone
		rig_class = find_rig_class(pb.rigify_type)
		draw_func = getattr(rig_class, self.draw_function_name)
		draw_func(layout, context, pb.rigify_parameters)

class CLOUDRIG_PT_params_parenting(CloudParamSubPanel):
	bl_label = "Parenting"
	draw_function_name = "draw_parenting_params"

class CLOUDRIG_PT_params_controls(CloudParamSubPanel):
	bl_label = "Controls"
	draw_function_name = "draw_control_params"
	bl_options = set()

class CLOUDRIG_PT_params_anim(CloudParamSubPanel):
	bl_label = "Test Animation"
	draw_function_name = "draw_anim_params"

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False
		return context.object.data.cloudrig_parameters.generate_test_action

	def draw_header(self, context):
		layout = self.layout
		pb = context.active_pose_bone
		params = pb.rigify_parameters
		layout.prop(params, 'CR_fk_chain_test_animation_generate', text="")

class CLOUDRIG_PT_params_bendy(CloudParamSubPanel):
	bl_label = "Bendy Bones"
	draw_function_name = "draw_bendy_params"
	bl_options = set()

class CLOUDRIG_PT_params_appearance(CloudParamSubPanel):
	bl_label = "Appearance"
	draw_function_name = "draw_appearance_params"

class CLOUDRIG_PT_params_custom_properties(CloudParamSubPanel):
	bl_label = "Custom Properties"
	draw_function_name = "draw_custom_prop_params"
	advanced_only = True

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False
		pb = context.active_pose_bone
		rig_class = find_rig_class(pb.rigify_type)
		return rig_class.is_using_custom_props(context, pb.rigify_parameters)

class CLOUDRIG_PT_params_bone_sets(CloudParamSubPanel):
	bl_label = "Bone Organization"
	draw_function_name = "draw_bone_sets_list"
	advanced_only = True

	@classmethod
	def poll(cls, context):
		if not super().poll(context):
			return False

		pb = context.active_pose_bone
		rig_class = find_rig_class(pb.rigify_type)

		# If no bone sets are visible, don't draw the panel.
		any_used = False
		for bsd in rig_class.bone_set_defs.values():
			if rig_class.is_bone_set_used(pb.rigify_parameters, bsd):
				any_used = True
				break
		return any_used

registry = [
	CLOUDRIG_PT_params_parenting
	,CLOUDRIG_PT_params_controls
	,CLOUDRIG_PT_params_anim
	,CLOUDRIG_PT_params_bendy
	,CLOUDRIG_PT_params_appearance
	,CLOUDRIG_PT_params_custom_properties
	,CLOUDRIG_PT_params_bone_sets
]