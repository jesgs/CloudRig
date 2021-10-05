from bpy.types import Panel, VIEW3D_PT_gizmo_display

class CLOUDRIG_PT_bone_gizmo_settings(Panel):
	"""Panel to draw gizmo settings for the active bone."""
	bl_label = "Custom Gizmo"
	bl_idname = "BONE_PT_CustomGizmo"
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_parent_id = "BONE_PT_display"

	@classmethod
	def poll(cls, context):
		ob = context.object
		pb = context.active_pose_bone
		return ob.type == 'ARMATURE' and pb

	def draw_header(self, context):
		props = context.active_pose_bone.cloudrig_gizmo
		layout = self.layout
		layout.prop(props, 'enabled', text="")

	def draw(self, context):
		overlay_enabled = context.scene.cloud_gizmos_enabled
		props = context.active_pose_bone.cloudrig_gizmo
		layout = self.layout
		layout.use_property_split = True
		layout.use_property_decorate = False
		layout = layout.column(align=True)

		if not overlay_enabled:
			layout.alert = True
			layout.label(text="CloudRig Gizmos are disabled in the Viewport Gizmos settings in the 3D View header.")
			return
		layout.enabled = props.enabled and overlay_enabled

		style_col = layout.column(align=True)
		style_col.row().prop(props, 'draw_style', expand=True)
		if props.draw_style == 'LINES':
			style_col.prop(props, 'line_width')
		if props.shape_object and \
				(
					(props.use_face_map and props.face_map_name in props.shape_object.face_maps) or \
					(not props.use_face_map and props.vertex_group_name in props.shape_object.vertex_groups)
				):
			style_col.enabled = False
		layout.prop(props, 'color')
		layout.prop(props, 'color_highlight')

		layout.row().prop(props, 'operator', expand=True)
		layout.prop(props, 'shape_object')
		if props.shape_object:
			row = layout.row(align=True)
			if props.use_face_map:
				row.prop_search(props, 'face_map_name', props.shape_object, 'face_maps', icon='FACE_MAPS')
				icon = 'FACE_MAPS'
			else:
				row.prop_search(props, 'vertex_group_name', props.shape_object, 'vertex_groups')
				icon = 'GROUP_VERTEX'
			row.prop(props, 'use_face_map', text="", emboss=False, icon=icon)

def VIEW3D_MT_cloudrig_gizmo_global_enable(self, context):
	col = self.layout.column()
	col.label(text="CloudRig")
	col.prop(context.scene, 'cloud_gizmos_enabled')

registry = [
	CLOUDRIG_PT_bone_gizmo_settings,
]

def register():
	VIEW3D_PT_gizmo_display.prepend(VIEW3D_MT_cloudrig_gizmo_global_enable)

def unregister():
	VIEW3D_PT_gizmo_display.remove(VIEW3D_MT_cloudrig_gizmo_global_enable)
