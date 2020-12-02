import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty, StringProperty, FloatProperty, PointerProperty
from .utils import naming
from .utils.ui import is_cloud_metarig

# This whole thing could be part of Rigify.

# TODO: UI doesn't currently communicate that an action should only be used by a singular ActionSlot.
# Although, does it have to be? I guess not...

def find_slot_by_action(rig, action):
	"""Find the CloudRigActionSlot in the rig which targets this action."""
	cloudrig = rig.data.cloudrig_parameters
	for i, slot in enumerate(cloudrig.action_slots):
		if slot.action==action:
			return slot, i

def poll_trigger_action(self, action):
	"""Whether an action can be used as a corrective action's trigger or not."""
	rig = bpy.context.object
	cloudrig = rig.data.cloudrig_parameters
	action_slots = cloudrig.action_slots
	active_slot = cloudrig.action_slots[cloudrig.active_action_slot_index]

	# If this action is the same as the active slot's action, don't show it.
	if action == active_slot.action:
		return False

	# If this action is used by any other action slot, show it.
	for slot in action_slots:
		if slot.action == action:
			return True

	return False

class CLOUDRIG_OT_Action_Remove(bpy.types.Operator):
	"""Remove an action setup"""

	bl_idname = "object.cloudrig_action_remove"
	bl_label = "Remove CloudRig Action Setup"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	index: IntProperty()

	@classmethod
	def poll(cls, context):
		cloudrig = context.object.data.cloudrig_parameters
		return len(cloudrig.action_slots)>0

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		action_slots = cloudrig.action_slots
		active_index = cloudrig.active_action_slot_index
		# This behaviour is inconsistent with other UILists in Blender, but I am right and they are wrong!
		to_index = active_index
		if to_index>len(action_slots)-2:
			to_index=len(action_slots)-2

		cloudrig.action_slots.remove(self.index)
		cloudrig.active_action_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Action_Add(bpy.types.Operator):
	"""Add an action setup"""

	bl_idname = "object.cloudrig_action_add"
	bl_label = "Add CloudRig Action Setup"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		action_slots = cloudrig.action_slots
		active_index = cloudrig.active_action_slot_index
		to_index = active_index + 1
		if len(action_slots)==0:
			to_index = 0

		cloudrig.action_slots.add()
		cloudrig.action_slots.move(len(cloudrig.action_slots)-1, to_index)
		cloudrig.active_action_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Action_Move(bpy.types.Operator):
	"""Move an action setup"""

	bl_idname = "object.cloudrig_action_move"
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
		return len(cloudrig.action_slots)>1

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		action_slots = cloudrig.action_slots
		active_index = cloudrig.active_action_slot_index
		to_index = active_index + (1 if self.direction=='DOWN' else -1)

		if to_index > len(action_slots)-1:
			to_index = 0
		if to_index < 0:
			to_index = len(action_slots)-1

		cloudrig.action_slots.move(active_index, to_index)
		cloudrig.active_action_slot_index = to_index

		return { 'FINISHED' }

class CLOUDRIG_OT_Action_Create(bpy.types.Operator):
	"""Create new Action"""
	# This is needed because bpy.ops.action.new() has a poll function that blocks
	# the operator unless it's drawn in an animation UI panel, which is dumb.

	bl_idname = "object.cloudrig_action_create"
	bl_label = "New"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	def execute(self, context):
		a = bpy.data.actions.new(name="Action")
		rig = context.object
		cloudrig = rig.data.cloudrig_parameters
		action_slot = cloudrig.action_slots[cloudrig.active_action_slot_index]
		if action_slot.action:
			# This could be an assert, it should never happen.
			self.report({'ERROR'}, "Action slot already has an action!")
			return {'CANCELLED'}
		action_slot.action = a
		return {'FINISHED'}

class CLOUDRIG_OT_Action_Jump(bpy.types.Operator):
	"""Set Active Action Slot Index"""

	bl_idname = "object.cloudrig_action_jump"
	bl_label = "Jump to Action Slot"
	bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

	to_index: IntProperty()

	def execute(self, context):
		cloudrig = context.object.data.cloudrig_parameters
		action_slots = cloudrig.action_slots
		cloudrig.active_action_slot_index = self.to_index

		return { 'FINISHED' }

class CLOUDRIG_UL_action_slots(bpy.types.UIList):
	def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
		rig = context.object
		cloudrig = data
		active_action = cloudrig.action_slots[cloudrig.active_action_slot_index]
		action_slot = item
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			if action_slot.action:
				row = layout.row()
				icon = 'ACTION'
				# Check if this action is a trigger for the active corrective action
				if active_action.is_corrective and \
					action_slot.action in [active_action.trigger_action_a, active_action.trigger_action_b]:
					icon = 'RESTRICT_INSTANCED_OFF'
				# Check if the active action is a trigger for this corrective action.
				if action_slot.is_corrective and active_action.action in [action_slot.trigger_action_a, action_slot.trigger_action_b]:
					icon = 'RESTRICT_INSTANCED_OFF'

				row.prop(action_slot.action, 'name', text="", emboss=False, icon=icon)

				target_rig = rig.data.rigify_target_rig
				if target_rig:
					subtarget_exists = action_slot.subtarget in target_rig.data.bones
					text = action_slot.subtarget
					icon = 'BONE_DATA'

					if action_slot.is_corrective:
						text = "Corrective"
						icon = 'RESTRICT_INSTANCED_OFF'
						if None in [action_slot.trigger_action_a, action_slot.trigger_action_b]:
							row.alert = True
							text = "Trigger Action missing!"
							icon = 'ERROR'
					elif not subtarget_exists:
						row.alert = True
						text = 'Control Bone missing!'
						icon = 'ERROR'

					row.label(text=text, icon=icon)

				icon = 'CHECKBOX_HLT' if action_slot.enabled else 'CHECKBOX_DEHLT'
				row.enabled = action_slot.enabled
				layout.prop(action_slot, 'enabled', text="", icon=icon, emboss=False)
			else:
				layout.label(text="", translate=False, icon='ACTION')
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'
			layout.label(text="", icon_value=icon)

class ActionSlot(bpy.types.PropertyGroup):
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

	is_corrective: BoolProperty(
		name = "Corrective"
		,description = "Indicate that this is a corrective action. Corrective actions will activate based on the activation of two other actions"
	)
	trigger_action_a: PointerProperty(
		name = "Trigger A"
		,description = "Action whose activation will trigger the corrective action"
		,type = bpy.types.Action
		,poll = poll_trigger_action
	)
	trigger_action_b: PointerProperty(
		name="Trigger B"
		,description = "Action whose activation will trigger the corrective action"
		,type = bpy.types.Action
		,poll = poll_trigger_action
	)
	show_action_a: BoolProperty(name="Show Settings")
	show_action_b: BoolProperty(name="Show Settings")
	corrective_type: EnumProperty(
		name = "Corrective Range"
		,items = [
			('NEGATIVE', 'A > 0.5', "This corrective action's evaluation time changes only when the evaluation time of trigger A is GREATER than 0.5"),
			('POSITIVE', 'A < 0.5', "This corrective action's evaluation time changes only when the evaluation time of trigger A is LESS than 0.5")
		]
	)

class CLOUDRIG_PT_actions(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = 'data'
	bl_label = "Rigify Actions"

	@classmethod
	def poll(cls, context):
		obj = context.object
		return is_cloud_metarig(context.object) and obj.mode in ('POSE', 'OBJECT')

	def draw(self, context):
		obj = context.object
		draw_cloudrig_actions(self.layout, obj)

def draw_cloudrig_actions(layout, rig):
	cloudrig = rig.data.cloudrig_parameters
	action_slots = cloudrig.action_slots
	active_index = cloudrig.active_action_slot_index

	row = layout.row()

	row.template_list(
		'CLOUDRIG_UL_action_slots',
		'',
		cloudrig,
		'action_slots',
		cloudrig,
		'active_action_slot_index',
	)

	col = row.column()
	col.operator('object.cloudrig_action_add', text="", icon='ADD')
	remove_op = col.operator('object.cloudrig_action_remove', text="", icon='REMOVE')
	remove_op.index = active_index
	col.separator()
	move_up_op = col.operator('object.cloudrig_action_move', text="", icon='TRIA_UP')
	move_up_op.direction='UP'
	move_down_op = col.operator('object.cloudrig_action_move', text="", icon='TRIA_DOWN')
	move_down_op.direction='DOWN'

	if len(action_slots)==0:
		return
	active_slot = action_slots[active_index]

	layout.template_ID(active_slot, 'action', new='object.cloudrig_action_create')
	if not active_slot.action:
		return

	layout = layout.column()
	layout.use_property_split=True
	layout.use_property_decorate=False
	layout.prop(active_slot, 'is_corrective')
	if active_slot.is_corrective:
		layout.prop(active_slot, 'corrective_type')
		layout.prop(active_slot, 'frame_start', text="Frame Start")
		layout.prop(active_slot, 'frame_end', text="End")
		layout.separator()
		for trigger_prop in ['trigger_action_a', 'trigger_action_b']:
			trigger = getattr(active_slot, trigger_prop)
			icon = 'ACTION' if active_slot.trigger_action_a else 'ERROR'
			row = layout.row()
			row.prop(active_slot, trigger_prop, icon=icon)
			if trigger:
				col = layout.column()
				col.enabled = False
				trigger_slot, slot_index = find_slot_by_action(rig, trigger)
				show_prop_name = 'show_action_' + trigger_prop[-1]
				show = getattr(active_slot, show_prop_name)
				icon = 'HIDE_OFF' if show else 'HIDE_ON'
				row.prop(active_slot, show_prop_name, icon=icon, text="")
				op = row.operator(CLOUDRIG_OT_Action_Jump.bl_idname, text="", icon='LOOP_FORWARDS')
				op.to_index = slot_index
				if show:
					draw_action_slot_properties(col, trigger_slot, rig.data.rigify_target_rig.data)
		return

	if not rig.data.rigify_target_rig:
		row = layout.row()
		row.alert=True
		row.label(text="Generate the rig to select a control bone for this action.")
		return

	draw_action_slot_properties(layout, active_slot, rig.data.rigify_target_rig.data)

def draw_action_slot_properties(layout, action_slot: ActionSlot, target_armature: bpy.types.Armature):
	row = layout.row()
	subtarget_exists = action_slot.subtarget in target_armature.bones
	icon = 'BONE_DATA' if subtarget_exists else 'ERROR'

	row.prop_search(action_slot, 'subtarget', target_armature, 'bones', icon=icon)
	row.alert = not subtarget_exists

	flipped_subtarget = naming.flip_name(action_slot.subtarget)
	flipped_subtarget_exists = flipped_subtarget in target_armature.bones
	if subtarget_exists and flipped_subtarget != action_slot.subtarget:
		row = layout.row()
		row.use_property_split=True
		text = f"Symmetrical ({flipped_subtarget})"
		if not flipped_subtarget_exists:
			text = text[:-1] + " not found!)"
		row.prop(action_slot, 'symmetrical', text=text)
		row.enabled = flipped_subtarget_exists

	if not subtarget_exists: return
	layout.prop(action_slot, 'frame_start', text="Frame Start")
	layout.prop(action_slot, 'frame_end', text="End")

	layout.prop(action_slot, 'target_space', text="Target Space")
	layout.prop(action_slot, 'transform_channel', text="Transform Channel")

	layout.prop(action_slot, 'trans_min')
	layout.prop(action_slot, 'trans_max')
	layout.separator()

classes = [
	ActionSlot,
	CLOUDRIG_UL_action_slots,
	CLOUDRIG_OT_Action_Add,
	CLOUDRIG_OT_Action_Remove,
	CLOUDRIG_OT_Action_Move,
	CLOUDRIG_OT_Action_Jump,
	CLOUDRIG_OT_Action_Create,
	CLOUDRIG_PT_actions,
]

def register():
	from bpy.utils import register_class
	for c in classes:
		register_class(c)

def unregister():
	from bpy.utils import unregister_class
	for c in reversed(classes):
		unregister_class(c)