import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty, EnumProperty
from mathutils.geometry import intersect_point_line

class CLOUDRIG_OT_FlattenChain(bpy.types.Operator):
	"""Flatten a chain of bones on a plane. Useful for perfect IK chains."""

	bl_idname = "object.cloudrig_flatten_bones"
	bl_label = "Flatten Bones"
	bl_options = {'REGISTER', 'UNDO'}

	use_selected: BoolProperty(name="Selected Bones", default=True)
	start_bone: StringProperty(name="Start bone")
	chain_length: IntProperty(name="Chain Length")
	axis: EnumProperty(name="Axis",
		items = [
			('X', 'X', 'X'),
			('Y', 'Y', 'Y'),
			('Z', 'Z', 'Z'),
		],
		default = 'Y'
	)

	@classmethod
	def poll(cls, context):
		return context.object and context.object.type=='ARMATURE'

	def execute(self, context):
		org_mode = context.mode
		bpy.ops.object.mode_set(mode='EDIT')

		rig = context.object

		bones = context.selected_editable_bones
		start_bone = context.active_bone
		if not self.use_selected:
			start_bone = rig.data.edit_bones.get(self.start_bone)
			if not start_bone:
				return {'CANCELLED'}
			bones = [start_bone]
			for i in range(self.chain_length):
				if len(bones[-1].children)==0:
					break
				bones.append(bones[-1].children[0])

		if len(bones)<2:
			return {'CANCELLED'}

		chain_start = bones[0].head
		chain_end = bones[-1].tail
		line = (chain_start, chain_end)

		bpy.ops.armature.select_all(action='DESELECT')

		for b in bones:
			b.select=True
			intersect = intersect_point_line(b.head, chain_start, chain_end)[0]
			if self.axis != 'X':
				b.head.x = intersect.x
			if self.axis != 'Y':
				b.head.y = intersect.y
			if self.axis != 'Z':
				b.head.z = intersect.z

		bpy.ops.armature.calculate_roll(type='GLOBAL_POS_Y')

		bpy.ops.object.mode_set(mode=org_mode)
		return { 'FINISHED' }

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_FlattenChain)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_FlattenChain)