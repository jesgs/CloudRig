import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty, StringProperty, FloatProperty, PointerProperty, CollectionProperty
from .utils import naming
from .utils.ui import is_cloud_metarig

# This whole thing could be part of Rigify.

class CLOUDRIG_OT_Parent_Remove(bpy.types.Operator):
	"""Remove a parent"""

	bl_idname = "object.cloudrig_parent_remove"
	bl_label = "Remove CloudRig Parent"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	index: IntProperty()

	@classmethod
	def poll(cls, context):
		pbone = context.active_pose_bone
		return len(pbone.rigify_parameters.CR_base_parent_slots)>0

	def execute(self, context):
		pbone = context.active_pose_bone
		parent_slots = pbone.rigify_parameters.CR_base_parent_slots
		active_index = pbone.rigify_parameters.CR_base_active_parent_slot_index
		# This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
		to_index = active_index
		if to_index>len(parent_slots)-2:
			to_index=len(parent_slots)-2

		parent_slots.remove(self.index)
		pbone.rigify_parameters.CR_base_active_parent_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Parent_Add(bpy.types.Operator):
	"""Add a parent"""

	bl_idname = "object.cloudrig_parent_add"
	bl_label = "Add CloudRig Parent"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	def execute(self, context):
		pbone = context.active_pose_bone
		parent_slots = pbone.rigify_parameters.CR_base_parent_slots
		active_index = pbone.rigify_parameters.CR_base_active_parent_slot_index
		to_index = active_index + 1
		if len(parent_slots)==0:
			to_index = 0

		parent_slots.add()
		parent_slots.move(len(parent_slots)-1, to_index)
		pbone.rigify_parameters.CR_base_active_parent_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Parent_Move(bpy.types.Operator):
	"""Move parent slot"""

	bl_idname = "object.cloudrig_parent_move"
	bl_label = "Move CloudRig Parent"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	direction: EnumProperty(
		name		 = "Direction"
		,items 		 = [
			('UP', 'UP', 'UP'),
			('DOWN', 'DOWN', 'DOWN'),
		]
		,default	 = 'UP'
	)

	@classmethod
	def poll(cls, context):
		pbone = context.active_pose_bone
		return len(pbone.rigify_parameters.CR_base_parent_slots)>1

	def execute(self, context):
		pbone = context.active_pose_bone
		parent_slots = pbone.rigify_parameters.CR_base_parent_slots
		active_index = pbone.rigify_parameters.CR_base_active_parent_slot_index
		to_index = active_index + (1 if self.direction=='DOWN' else -1)

		if to_index > len(parent_slots)-1:
			to_index = 0
		if to_index < 0:
			to_index = len(parent_slots)-1

		parent_slots.move(active_index, to_index)
		pbone.rigify_parameters.CR_base_active_parent_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_UL_parent_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		metarig = context.object
		rig = metarig.data.rigify_target_rig
		pbone = context.active_pose_bone
		for i, parent_slot in enumerate(pbone.rigify_parameters.CR_base_parent_slots):
			if item==parent_slot:
				break
		parent_slot = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			row = layout.row()
			row.prop(parent_slot, 'name', text=f"Parent {i} UI Name:", emboss=True, icon='FILE_TEXT')
			row.prop_search(parent_slot, 'bone', rig.data, 'bones')
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class ParentSlot(bpy.types.PropertyGroup):
	name: StringProperty(name="Name", description="Name to display in the UI")
	bone: StringProperty(name="Bone", description="Bone to use as the available parent")

def draw_cloudrig_parents(layout, pbone):
	active_index = pbone.rigify_parameters.CR_base_active_parent_slot_index

	row = layout.row()

	row.template_list(
		'CLOUDRIG_UL_parent_slots',
		'',
		pbone.rigify_parameters,
		'CR_base_parent_slots',
		pbone.rigify_parameters,
		'CR_base_active_parent_slot_index',
	)

	col = row.column()
	col.operator('object.cloudrig_parent_add', text="", icon='ADD')
	remove_op = col.operator('object.cloudrig_parent_remove', text="", icon='REMOVE')
	remove_op.index = active_index
	col.separator()
	move_up_op = col.operator('object.cloudrig_parent_move', text="", icon='TRIA_UP')
	move_up_op.direction = 'UP'
	move_down_op = col.operator('object.cloudrig_parent_move', text="", icon='TRIA_DOWN')
	move_down_op.direction = 'DOWN'

classes = [
	ParentSlot,
	CLOUDRIG_UL_parent_slots,
	CLOUDRIG_OT_Parent_Add,
	CLOUDRIG_OT_Parent_Remove,
	CLOUDRIG_OT_Parent_Move,
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)