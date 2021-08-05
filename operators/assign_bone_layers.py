import bpy
from bpy.props import BoolVectorProperty
from ..generation.cloudrig import (is_active_cloudrig, is_active_cloud_metarig, 
									draw_layers_ui, register_hotkey)

class CLOUDRIG_OT_layer_select(bpy.types.Operator):
	"""Assign active layers for selected bones using the named Rigify layers"""
	bl_idname = "pose.cloudrig_assign_layers"
	bl_label = "Assign Bone Layers"
	bl_options = {'REGISTER', 'UNDO'}

	def update_layers(self, context):
		for pb in context.selected_pose_bones:
			pb.bone.layers = self.layers[:]
		for i, layer in enumerate(self.layers):
			if context.object.data.layers[i] == False and layer == True:
				context.object.data.layers[i] = True

	layers: BoolVectorProperty(size = 32, subtype = 'LAYER', description = f"Layers to assign selected bones to", update=update_layers)

	@classmethod
	def poll(cls, context):
		return is_active_cloudrig(context) or is_active_cloud_metarig(context)

	def invoke(self, context, event):
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def draw(self, context):
		draw_layers_ui(self.layout, context.object, show_hidden_checkbox=True, owner=self)

	def execute(self, context):
		return {'FINISHED'}

def register():
	from bpy.utils import register_class
	register_class(CLOUDRIG_OT_layer_select)

	register_hotkey(CLOUDRIG_OT_layer_select.bl_idname
		,hotkey_kwargs = {'type': "M", 'value': "PRESS"}
		,key_cat = "Pose"
		,space_type = 'VIEW_3D'
	)
	register_hotkey(CLOUDRIG_OT_layer_select.bl_idname
		,hotkey_kwargs = {'type': 'M', 'value': 'PRESS'}
		,key_cat = 'Armature'
	)

def unregister():
	from bpy.utils import unregister_class
	unregister_class(CLOUDRIG_OT_layer_select)