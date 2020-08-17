# This file is unused.

# I tried implementing Bone Sets as a UIList. This would make the UI a lot nicer.
# There are a host of issues with it though.

# Rigify won't let us register CollectionProperties because https://developer.blender.org/diffusion/BA/browse/master/rigify/__init__.py$434 - CollectionProperties don't have an update function, so this line errors.
# Even if it did allow us, we couldn't populate the CollectionProperty from any of the rig object classmethods or drawing functions because wrong context.
# So the best we could do is add a button to populate the list, or do it in the update callback of the BoneSet hide toggle or something like that...

import bpy
from bpy.props import StringProperty, IntProperty, CollectionProperty

from rigify import rig_lists

class BoneSetDefinition(bpy.types.PropertyGroup):
	param_name: StringProperty()
	layer_param_name: StringProperty()
	ui_name: StringProperty()
	preset: IntProperty()
	override: StringProperty()

class CLOUDRIG_UL_bone_set_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		rig = context.object
		cloudrig = data
		boneset = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(boneset, 'name', emboss=True)
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

def find_rig_class(rig_type):
	rig_module = rig_lists.rigs[rig_type]["module"]

	return rig_module.Rig

def draw_bone_set_list(layout, params):
	context = bpy.context
	bone = context.active_pose_bone
	# ensure_bone_set_definitions(bone, params, context)

	row = layout.row()
	row.template_list(
		'CLOUDRIG_UL_bone_set_slots',
		'',
		params,
		'bone_sets',
		bone,
		'cloudrig_active_bone_set_index',
	)

classes = [
	BoneSetDefinition,
	CLOUDRIG_UL_bone_set_slots
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)
	bpy.types.PoseBone.cloudrig_bone_sets = CollectionProperty(type=BoneSetDefinition)
	bpy.types.PoseBone.cloudrig_active_bone_set_index = IntProperty(min=0)

def unregister():
	from bpy.utils import unregister_class
	for c in classes:
		unregister_class(c)
	
	del bpy.types.PoseBone.rigify_parameters.bone_sets
	del bpy.types.PoseBone.rigify_parameters.active_bone_set_index
