import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty, StringProperty, FloatProperty, PointerProperty
from .utils import naming
from .utils.ui import is_cloud_metarig

# This whole thing could be part of Rigify.

# TODO: UI doesn't currently communicate that an action should only be used by a singular ActionSlot.
# Although, does it have to be? I guess not...

def find_slot_by_action(metarig_data, action):
	"""Find the CloudRigActionSlot in the rig which targets this action."""
	cloudrig = metarig_data.cloudrig_parameters
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

	frame_start: IntProperty(
		name		 = "Start Frame"
		,description = "First frame of the action's timeline"
	)
	frame_end: IntProperty(
		name		 = "End Frame"
		,default	 = 2
		,description = "Last frame of the action's timeline"
	)
	trans_min: FloatProperty(
		name		 = "Min"
		,default	 = -0.05
		,description = "Value that the transformation value must reach to put the action's timeline to the first frame. Rotations are in degrees"
	)
	trans_max: FloatProperty(
		name		 = "Max"
		,default	 = 0.05
		,description = "Value that the transformation value must reach to put the action's timeline to the last frame. Rotations are in degrees"
	)

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

	@property
	def keyed_bones_names(self) -> [str]:
		"""Return a list of bone names that have keyframes in the Action of this Slot."""
		keyed_bones = []
		for fc in self.action.fcurves:
			# Extracting bone name from fcurve data path
			if "pose.bones" not in fc.data_path: continue
			bone_name = fc.data_path.split('["')[1].split('"]')[0]

			if bone_name not in keyed_bones:
				keyed_bones.append(bone_name)

		return keyed_bones

	def get_constraint_name(self, bone_name:str):
		# Determine what the name of the constraint created by this Action Slot would be on a given bone.
		control_is_left_side = naming.side_is_left(self.subtarget)
		bone_is_left_side = naming.side_is_left(bone_name)
		do_symmetry = control_is_left_side!=None and self.symmetrical==True

		con_name = "Action_" + self.action.name
		left_con_name = con_name + ".L"
		right_con_name = con_name + ".R"

		if do_symmetry:
			# If Symmetry is enabled but the bone doesn't have a side, it will be split into two constraints, so return a list.
			if bone_is_left_side==None:
				return [left_con_name, right_con_name]

			if bone_is_left_side:
				return left_con_name
			else:
				return right_con_name
		
		return con_name

	def create_action_constraints(self, property_bone_name):
			# Getting a list of pose bones that have keyframes on this action
			control_is_left_side = naming.side_is_left(self.subtarget)
			do_symmetry = control_is_left_side!=None and self.symmetrical==True

			metarig_data = self.id_data
			rig = metarig_data.rigify_target_rig

			action = self.action
			subtarget = self.subtarget

			# Adding action constraints to the bones
			for bn in self.keyed_bones_names:
				pb = rig.pose.bones.get(bn)
				if not pb: continue
				con_name = "Action_" + action.name
				constraints = []

				bone_is_left_side = naming.side_is_left(pb.name)

				# If bone name is unflippable...
				if bone_is_left_side==None:
					#...but target bone name is flippable, we assume that this keyed_bone is
					# a center bone, so we split constraint in two.
					if do_symmetry:
						c_l = pb.constraints.new(type='ACTION')
						c_l.name = con_name + ".L"
						c_l.influence = 0.5
						constraints.append(c_l)
						c_r = pb.constraints.new(type='ACTION')
						c_r.influence = 0.5
						c_r.name = con_name + ".R"
						constraints.append(c_r)
					else:
						# if target bone name is not flippable or symmetry is disabled, 
						# add the constraint normally.
						c = pb.constraints.new(type='ACTION')
						c.name = con_name
						constraints.append(c)
				else:
					# Constraint name should indicate side
					c = pb.constraints.new(type='ACTION')
					if do_symmetry:
						con_name += ".L" if bone_is_left_side else ".R"
					c.name = con_name
					constraints.append(c)

				# Configure Action constraints
				for c in constraints:
					# If constraint is not the same side as the control, flip it.
					if do_symmetry:
						constraint_is_left_side = naming.side_is_left(c.name)
						control_is_left_side = naming.side_is_left(subtarget)
						if constraint_is_left_side != control_is_left_side:
							subtarget = naming.flip_name(subtarget)
					c.target_space = self.target_space
					c.transform_channel = self.transform_channel
					c.target = rig
					c.subtarget = subtarget
					c.action = action
					# TODO: Some of this could be removed if we always use Evaluation Time feature. (Once we break 2.92 backwards comp)
					c.min = self.trans_min
					c.max = self.trans_max
					c.frame_start = self.frame_start
					c.frame_end = self.frame_end
					c.mix_mode = 'BEFORE'
					if c.subtarget != self.subtarget:
						# Flip min/max in some cases.
						if c.transform_channel in ['ROTATION_Z', 'LOCATION_X']:
							max_tmp = c.max
							c.max = c.min
							c.min = max_tmp

					# Move constraints to top of the stack in the same order. 
					# Important that Action constraints are above Armature constraints.
					pb.constraints.move(len(pb.constraints)-1, 0)

					if self.is_corrective:
						c.use_eval_time = True
						fcurve = rig.driver_add(f'pose.bones["{pb.name}"].constraints["{c.name}"].eval_time')
						driver = fcurve.driver
						trigger_a_slot, i = find_slot_by_action(metarig_data, self.trigger_action_a)
						trigger_b_slot, i = find_slot_by_action(metarig_data, self.trigger_action_b)
						trigger_a_con_name = trigger_a_slot.get_constraint_name(pb.name)
						trigger_b_con_name = trigger_b_slot.get_constraint_name(pb.name)

						relation = ">=" if self.corrective_type=='POSITIVE' else "<="
						sign = "-" if self.corrective_type=='POSITIVE' else "+"
						# This expression calculates the correct value for this corrective action's eval_time.
						driver.expression = f'0.5 if A {relation} 0.5 else 0.5 {sign} (B-0.5) * (A-0.5) *2'

						# For example, let's say you have these two actions:
						# A = Lips_UpDown.eval_time
						var_a = driver.variables.new()
						var_a.name = "A"
						target_a = var_a.targets[0]
						target_a.data_path = f'pose.bones["{property_bone_name}"]["{trigger_a_con_name}"]'
						# B = Lips_ThinWide.eval_time
						var_b = driver.variables.new()
						var_b.name = "B"
						target_b = var_b.targets[0]
						target_b.data_path = f'pose.bones["{property_bone_name}"]["{trigger_b_con_name}"]'

						target_a.id = target_b.id = rig
						continue

					# Set up usage with Evaluation Time feature and a driver instead of old setup
					if not hasattr(c, 'use_eval_time'):
						continue

					c.use_eval_time = True
					# Add driven custom properties to the Action Helper bone that mirror the eval_time of each action.
					data_paths = [
						f'pose.bones["{pb.name}"].constraints["{c.name}"].eval_time'
					]
					property_storage = rig.pose.bones.get(property_bone_name)
					assert property_storage, f"Error: Action property storage bone {property_bone_name} not found!"
					property_storage[c.name] = 0.5
					data_paths.append(
						f'pose.bones["{property_bone_name}"]["{c.name}"]'
					)
					for data_path in data_paths:
						exists = rig.animation_data.drivers.find(data_path)
						if exists:
							continue
						fcurve = rig.driver_add(data_path)
						driver = fcurve.driver

						var_range = c.max - c.min
						range_mid = c.min + (c.max - c.min)/2

						expression = f'(var - {range_mid}) / {var_range} + 0.5'
						if range_mid==0:
							expression = f'var / {var_range} + 0.5'

						# Convert rotation to degrees as promised in the tooltip.
						if 'ROTATION' in self.transform_channel:
							expression = expression.replace('var', 'var*180/pi')

						driver.expression = expression
						var = driver.variables.new()
						var.type = 'TRANSFORMS'
						target = var.targets[0]
						target.id = rig
						target.bone_target = subtarget
						target.transform_type = c.transform_channel.replace("ATION", "")
						target.transform_space = c.target_space + "_SPACE"
						target.rotation_mode = 'SWING_TWIST_Y'

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

def draw_cloudrig_actions(layout, metarig):
	cloudrig = metarig.data.cloudrig_parameters
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
				trigger_slot, slot_index = find_slot_by_action(metarig.data, trigger)
				show_prop_name = 'show_action_' + trigger_prop[-1]
				show = getattr(active_slot, show_prop_name)
				icon = 'HIDE_OFF' if show else 'HIDE_ON'
				row.prop(active_slot, show_prop_name, icon=icon, text="")
				op = row.operator(CLOUDRIG_OT_Action_Jump.bl_idname, text="", icon='LOOP_FORWARDS')
				op.to_index = slot_index
				if show:
					draw_action_slot_properties(col, trigger_slot, metarig.data.rigify_target_rig.data)
		return

	if not metarig.data.rigify_target_rig:
		row = layout.row()
		row.alert=True
		row.label(text="Generate the rig to select a control bone for this action.")
		return

	draw_action_slot_properties(layout, active_slot, metarig.data.rigify_target_rig.data)

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