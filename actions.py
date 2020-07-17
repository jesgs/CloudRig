import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty, StringProperty, FloatProperty, PointerProperty

from .utils import flip_name

class CLOUDRIG_OT_Action_Remove(bpy.types.Operator):
	"""Remove an action setup"""

	bl_idname = "pose.cloudrig_action_remove"
	bl_label = "Remove CloudRig Action Setup"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	index: IntProperty()

	@classmethod
	def poll(cls, context):
		cloudrig = context.object.data.cloudrig_parameters
		return len(cloudrig.actions)>0

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		actions = cloudrig.actions
		active_index = cloudrig.active_action_index
		# This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
		to_index = active_index
		if to_index>len(actions)-2:
			to_index=len(actions)-2

		cloudrig.actions.remove(self.index)
		cloudrig.active_action_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Action_Add(bpy.types.Operator):
	"""Add an action setup"""

	bl_idname = "pose.cloudrig_action_add"
	bl_label = "Add CloudRig Action Setup"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		actions = cloudrig.actions
		active_index = cloudrig.active_action_index
		to_index = active_index + 1
		if len(actions)==0:
			to_index = 0

		cloudrig.actions.add()
		cloudrig.active_action_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Action_Move(bpy.types.Operator):
	"""Move an action setup"""

	bl_idname = "pose.cloudrig_action_move"
	bl_label = "Move CloudRig Action Setup"
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
		cloudrig = context.object.data.cloudrig_parameters
		return len(cloudrig.actions)>1

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		actions = cloudrig.actions
		active_index = cloudrig.active_action_index
		to_index = active_index + (1 if self.direction=='DOWN' else -1)

		if to_index > len(actions)-1:
			to_index = 0
		if to_index < 0:
			to_index = len(actions)-1

		cloudrig.actions.move(active_index, to_index)
		cloudrig.active_action_index = to_index

		return { 'FINISHED' }


class CLOUDRIG_UL_action_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		rig = context.object
		cloudrig = data
		act = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			if act.action:
				row = layout.row()
				row.prop(act.action, 'name', text="", emboss=False, icon='ACTION')

				target_rig = rig.data.rigify_target_rig
				if target_rig:
					subtarget_exists = act.subtarget in target_rig.data.bones
					if not subtarget_exists:
						row.label(text='Control Bone missing!', icon='ERROR')
					else:
						row.label(text=act.subtarget, icon='BONE_DATA')

				# icon = 'HIDE_OFF' if act.enabled else 'HIDE_ON'
				icon = 'CHECKBOX_HLT' if act.enabled else 'CHECKBOX_DEHLT'
				row.enabled = act.enabled
				layout.prop(act, 'enabled', text="", icon=icon, emboss=False)
			else:
				layout.label(text="", translate=False, icon='ACTION')
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class CloudRigAction(bpy.types.PropertyGroup):
	enabled: BoolProperty(
		name="Enabled"
		,description = "Create constraints for this action on the generated rig"
		,default=True
	)
	symmetrical: BoolProperty(
		name="Symmetrical"
		,description = "Apply the same setup but mirrored to the opposite side control, shown in parentheses. Bones will only be affected by the control with the same side (eg., .L bones will only be affected by the .L control). Bones without a side in their name (so no .L or .R) will be affected by both controls with 0.5 influence each"
		,default=True
	)
	action: PointerProperty(name="Action", type=bpy.types.Action)
	subtarget: StringProperty(name="Control Bone", description="Select a bone on the generated rig which will drive this action")

	transform_channel: EnumProperty(name="Transform Channel",
		items=[("LOCATION_X", "X Location", "X Location"),
				("LOCATION_Y", "Y Location", "Y Location"),
				("LOCATION_Z", "Z Location", "Z Location"),
				("ROTATION_X", "X Rotation", "X Rotation"),
				("ROTATION_Y", "Y Rotation", "Y Rotation"),
				("ROTATION_Z", "Z Rotation", "Z Rotation"),
				("SCALE_X", "X Scale", "X Scale"),
				("SCALE_Y", "Y Scale", "Y Scale"),
				("SCALE_Z", "Z Scale", "Z Scale")
				],
		description="Transform channel",
		default="LOCATION_X")

	target_space: EnumProperty(name="Transform Space",
		items=[("WORLD", "World Space", "World Space"),
		("POSE", "Pose Space", "Pose Space"),
		("LOCAL_WITH_PARENT", "Local With Parent", "Local With Parent"),
		("LOCAL", "Local Space", "Local Space")
		],

		default="LOCAL"
	)

	frame_start: IntProperty(name="Start Frame")
	frame_end: IntProperty(name="End Frame",
		default=2)
	trans_min: FloatProperty(name="Min",
		default=-0.05)
	trans_max: FloatProperty(name="Max",
		default=0.05)

def draw_cloudrig_actions(layout, rig):
	cloudrig = rig.data.cloudrig_parameters
	actions = cloudrig.actions
	active_index = cloudrig.active_action_index

	row = layout.row()

	row.template_list(
		'CLOUDRIG_UL_action_slots',
		'',
		cloudrig,
		'actions',
		cloudrig,
		'active_action_index',
	)

	col = row.column()
	col.operator('pose.cloudrig_action_add', text="", icon='ADD')
	remove_op = col.operator('pose.cloudrig_action_remove', text="", icon='REMOVE')
	remove_op.index = active_index
	col.separator()
	move_up_op = col.operator('pose.cloudrig_action_move', text="", icon='TRIA_UP')
	move_up_op.direction='UP'
	move_down_op = col.operator('pose.cloudrig_action_move', text="", icon='TRIA_DOWN')
	move_down_op.direction='DOWN'

	if len(actions)==0:
		return
	act = actions[active_index]

	layout.template_ID(act, 'action', new='action.new')
	if not act.action:
		return

	# layout.prop_search(act, 'subtarget', rig.data, 'bones')
	if not rig.data.rigify_target_rig:
		row = layout.row()
		row.alert=True
		row.label(text="Generate the rig to select a control bone for this action.")
		return

	layout = layout.column()
	layout.use_property_split=True
	layout.use_property_decorate=False
	row = layout.row()
	subtarget_exists = act.subtarget in rig.data.rigify_target_rig.data.bones
	icon = 'BONE_DATA' if subtarget_exists else 'ERROR'
	flipped_subtarget = flip_name(act.subtarget)
	row.prop_search(act, 'subtarget', rig.data.rigify_target_rig.data, 'bones', icon=icon)
	row.alert = not subtarget_exists

	if subtarget_exists and (act.subtarget.endswith(".L") or act.subtarget.endswith(".R")):
		row = layout.row()
		row.use_property_split=True
		row.prop(act, 'symmetrical', text=f"Symmetrical ({flipped_subtarget})")

	if not subtarget_exists: return
	layout.prop(act, 'frame_start', text="Frame Start")
	layout.prop(act, 'frame_end', text="End")

	layout.prop(act, 'target_space', text="Target Space")
	layout.prop(act, 'transform_channel', text="Transform Channel")

	layout.prop(act, 'trans_min')
	layout.prop(act, 'trans_max')
	layout.separator()

classes = [
	CloudRigAction,
	CLOUDRIG_UL_action_slots,
	CLOUDRIG_OT_Action_Add,
	CLOUDRIG_OT_Action_Remove,
	CLOUDRIG_OT_Action_Move
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)