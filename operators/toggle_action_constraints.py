import bpy
from bpy.props import BoolProperty

class CLOUDRIG_OT_Toggle_Action_Constraints(bpy.types.Operator):
	"""Toggle Action constraints of the active action on all bones of the armature"""
	bl_idname = "armature.toggle_action_constraints"
	bl_label = "Toggle Action Constraints"
	bl_options = {'REGISTER', 'UNDO'}

	enable: BoolProperty(name="Enable", default=True)

	@staticmethod
	def get_first_referencing_constraint(rig, action: bpy.types.Action) -> bpy.types.Constraint:
		for pb in rig.pose.bones:
			for c in pb.constraints:
				if c.type == 'ACTION' and c.action == action:
					return c

	@classmethod
	def poll(cls, context):
		ob = context.object
		if not ob or ob.type != 'ARMATURE' or ob.mode not in ['POSE', 'OBJECT']:
			return
		if not (ob.animation_data and ob.animation_data.action):
			return
		action = ob.animation_data.action
		con = cls.get_first_referencing_constraint(ob, action)
		return con != None

	def execute(self, context):
		rig = context.object
		action = rig.animation_data.action

		con_count = 0
		for pb in rig.pose.bones:
			for c in pb.constraints:
				if c.type == 'ACTION' and c.action == action:
					c.mute = not self.enable
					con_count += 1
		
		word = "Enabled" if self.enable else "Disabled"
		self.report({'INFO'}, f'{word} {con_count} constraints referencing "{action.name}"')

		return { 'FINISHED' }

def draw_toggle_but(self, context):
	layout = self.layout
	st = context.space_data
	if st.mode != 'ACTION':
		return
	if not CLOUDRIG_OT_Toggle_Action_Constraints.poll(context):
		return
	first_con = CLOUDRIG_OT_Toggle_Action_Constraints.get_first_referencing_constraint(context.object, context.object.animation_data.action)
	word = "Disable" if first_con.enabled else "Enable"
	op = layout.operator(CLOUDRIG_OT_Toggle_Action_Constraints.bl_idname, text=word + " Constraints", icon='CONSTRAINT_BONE')
	op.enable = not first_con.enabled

registry = [
	CLOUDRIG_OT_Toggle_Action_Constraints
]

def register():
	bpy.types.DOPESHEET_HT_header.append(draw_toggle_but)

def unregister():
	bpy.types.DOPESHEET_HT_header.remove(draw_toggle_but)