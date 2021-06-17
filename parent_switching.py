import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty, StringProperty, FloatProperty, PointerProperty, CollectionProperty
from .utils import naming
from .utils.ui import is_cloud_metarig
from .utils.ui_list import draw_ui_list

# This whole thing could be part of Rigify.

class CLOUDRIG_UL_parent_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		pbone = context.active_pose_bone
		parent_slot = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(parent_slot, 'name', text=f"", emboss=True)
			row.prop_search(parent_slot, 'bone', rig.data, 'bones', text="")
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class ParentSlot(bpy.types.PropertyGroup):
	name: StringProperty(name="Name", description="Name to display in the UI for this parent option")
	bone: StringProperty(name="Bone", description="Bone that will be used as the parent")

def draw_cloudrig_parents(layout, context):
	pbone = context.active_pose_bone
	active_index = pbone.rigify_parameters.CR_base_active_parent_slot_index

	draw_ui_list(
		layout
		,context
		,class_name = 'CLOUDRIG_UL_parent_slots'
		,list_context_path = 'active_pose_bone.rigify_parameters.CR_base_parent_slots'
		,active_idx_context_path = 'active_pose_bone.rigify_parameters.CR_base_active_parent_slot_index'
	)

classes = [
	ParentSlot,
	CLOUDRIG_UL_parent_slots,
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)