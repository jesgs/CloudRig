# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Menu, PoseBone, Operator
from bpy.props import EnumProperty
from mathutils import Matrix

from ..generation.cloudrig import find_metarig_of_rig
from ..rig_component_features.widgets.widgets import ensure_widget, get_widgets_enum_items, LIBRARY_WIDGETS
from ..rig_component_features.object import EnsureVisible
from ..bs_utils.hotkeys import register_hotkey

class POSE_OT_unassign_custom_shape(Operator):
    """Unassign custom shapes from all selected pose bones"""

    bl_idname = "pose.unassign_custom_shape"
    bl_label = "Unassign Custom Shape"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not context.selected_pose_bones:
            return False
        for pb in context.selected_pose_bones:
            if pb.custom_shape:
                return True

        cls.poll_message_set("No selected bones have a custom shape.")
        return False

    def execute(self, context):
        counter = 0
        for pb in context.selected_pose_bones:
            if pb.custom_shape:
                counter += 1
                pb.custom_shape = None

        self.report({'INFO'}, f"Bone shapes unassigned: {counter}.")

        return {'FINISHED'}


class POSE_OT_assign_selected_custom_shape(Operator):
    """Assign a CloudRig custom shape or an object whose name starts with WGT- to the selected pose bones"""

    bl_idname = "pose.assign_selected_custom_shape"
    bl_label = "Select Custom Shape"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    widget_shape: EnumProperty(
        name="Widget Shape",
        description="Choose a custom shape from CloudRig's library as well as any objects in the current file prefixed with 'WGT-'",
        items=get_widgets_enum_items,
    )

    def invoke(self, context, _event):
        self.widget_shape = 'WGT-Cube'
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, 'widget_shape')

    @classmethod
    def poll(cls, context):
        if not context.selected_pose_bones:
            cls.poll_message_set("No selected pose bones.")
            return False
        return True

    def execute(self, context):
        widget = ensure_widget(self.widget_shape, overwrite=False)
        coll = context.scene.collection
        rig_ob = find_metarig_of_rig(context, context.pose_object) or context.pose_object
        if rig_ob.cloudrig.generator.widget_collection:
            coll = rig_ob.cloudrig.generator.widget_collection
        if widget not in set(coll.all_objects):
            coll.objects.link(widget)
        counter = 0
        for pb in context.selected_pose_bones:
            if pb.custom_shape != widget:
                pb.custom_shape = widget
                counter += 1

        self.report({'INFO'}, f"Shapes assigned to bones: {counter}.")

        return {'FINISHED'}


class POSE_OT_reload_selected_custom_shape(Operator):
    """Reload custom shapes of selected pose bones from the Widgets.blend file"""

    bl_idname = "pose.reload_custom_shapes"
    bl_label = "Reload Custom Shapes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @staticmethod
    def get_bones_to_reload(context):
        if not context.selected_pose_bones:
            return
        for pb in context.selected_pose_bones:
            if (
                pb.custom_shape
                and not pb.custom_shape.library
                and pb.custom_shape.name in [wgt_tup[0] for wgt_tup in LIBRARY_WIDGETS]
            ):
                yield pb

    @classmethod
    def poll(cls, context):
        if any(cls.get_bones_to_reload(context)):
            return True

        cls.poll_message_set("No selected bones use a CloudRig custom shape.")
        return False

    def execute(self, context):
        for i, pb in enumerate(self.get_bones_to_reload(context)):
            pb.custom_shape = ensure_widget(pb.custom_shape.name, overwrite=True)

        self.report({'INFO'}, f"Bone shapes reloaded: {i+1}.")

        return {'FINISHED'}


class POSE_OT_copy_custom_shape_to_selected_bones(Operator):
    """Copy custom shape of the active bone to all selected bones"""

    bl_idname = "pose.copy_custom_shape_to_selected_bones"
    bl_label = "Copy to Selected"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not context.active_pose_bone:
            cls.poll_message_set("No active pose bone.")
            return False
        if len(context.selected_pose_bones) < 2:
            cls.poll_message_set("At least two bones must be selected.")
            return False
        return True

    def execute(self, context):
        active_pb = context.active_pose_bone
        for i, pb in enumerate(context.selected_pose_bones):
            pb.custom_shape = active_pb.custom_shape
            pb.custom_shape_scale_xyz = active_pb.custom_shape_scale_xyz
            pb.custom_shape_translation = active_pb.custom_shape_translation
            pb.custom_shape_rotation_euler = active_pb.custom_shape_rotation_euler
            pb.custom_shape_transform = active_pb.custom_shape_transform
            pb.use_custom_shape_bone_size = active_pb.use_custom_shape_bone_size
            pb.bone.show_wire = active_pb.bone.show_wire

        self.report({'INFO'}, f"Copied shape to bones: {i}.")

        return {'FINISHED'}


widgets_visible = []


class POSE_OT_edit_widget_of_selected_bones(Operator):
    """Edit custom shape of selected bones"""

    bl_idname = "pose.edit_widget_of_selected_bones"
    bl_label = "Edit Custom Shapes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll_without_linked_check(cls, context):
        pb = context.active_pose_bone
        if context.mode != 'POSE':
            cls.poll_message_set("Must be in pose mode.")
            return False
        if len(context.selected_pose_bones) == 0:
            cls.poll_message_set("Must have a selected pose bone.")
            return False
        if not any([pb.custom_shape for pb in context.selected_pose_bones]):
            cls.poll_message_set("At least one selected bone must have a custom shape.")
            return False
        return True

    @classmethod
    def poll(cls, context):
        if not cls.poll_without_linked_check(context):
            return False

        if all(
            [
                pb.custom_shape.library
                for pb in context.selected_pose_bones
                if pb.custom_shape
            ]
        ):
            cls.poll_message_set(
                "All selected bones' custom shapes are linked, they cannot be edited."
            )
            return False

        return True

    def enter_custom_shape_edit_mode(self, context):
        rig = context.active_object

        # Reveal widgets of selected bones.
        global widgets_visible
        active_shape = None
        for pb in context.selected_pose_bones:
            if pb.custom_shape and not pb.custom_shape.library:
                widgets_visible.append(EnsureVisible(context, pb.custom_shape))
                active_shape = pb.custom_shape
                self.transform_widget_to_bone(pb, select=True)

        # Enter mesh edit mode on the now visible bone shapes.
        context.scene['widget_edit_armature'] = rig.name
        context.view_layer.objects.active = active_shape
        bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def transform_widget_to_bone(pb: PoseBone, select=False):
        """Transform a pose bone's custom shape object to match the bone's visual transforms."""
        shape = pb.custom_shape
        assert shape, "No shape to edit."

        if select:
            shape.select_set(True)

        # Step 1: Account for Override Transform
        transform_bone = pb
        if pb.custom_shape_transform:
            transform_bone = pb.custom_shape_transform

        # Step 2: Account for additional scaling from use_custom_shape_bone_size,
        # which scales the shape by the bone length.
        scale = pb.custom_shape_scale_xyz.copy()
        if pb.use_custom_shape_bone_size:
            scale *= pb.bone.length

        # Step 3: Create a matrix from the custom shape translation, rotation
        # and this scale which already accounts for bone length.
        custom_shape_matrix = Matrix.LocRotScale(
            pb.custom_shape_translation, pb.custom_shape_rotation_euler, scale
        )

        # Step 4: Multiply the pose bone's world matrix by the custom shape matrix.
        final_matrix = transform_bone.matrix @ custom_shape_matrix

        # Step 5: Apply this matrix to the object.
        # It should now match perfectly with the visual transforms of the pose bone,
        # unless there is skew.
        shape.matrix_world = final_matrix

    def execute(self, context):
        self.enter_custom_shape_edit_mode(context)

        return {'FINISHED'}


class MESH_OT_return_to_pose_mode(Operator):
    """Return from custom shape editing back to the rig"""

    bl_idname = "mesh.return_to_pose_mode"
    bl_label = "Edit Custom Shape"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not 'widget_edit_armature' in context.scene:
            cls.poll_message_set("Cannot return to rig (No name stored).")
            return False
        rig = bpy.data.objects.get(context.scene['widget_edit_armature'])
        if not rig:
            cls.poll_message_set("Cannot return to rig (Stored name is invalid).")
            return False

        return True

    @staticmethod
    def restore_all_widgets_visibility(context):
        global widgets_visible

        if widgets_visible != []:
            for w in widgets_visible[:]:
                try:
                    w.restore(context)
                except:
                    pass
        widgets_visible = []

    def execute(self, context):
        shape_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        for shape_obj in shape_objs:
            shape_obj.select_set(False)
        bpy.ops.object.mode_set(mode='OBJECT')
        self.restore_all_widgets_visibility(context)

        rig = bpy.data.objects.get((context.scene['widget_edit_armature'], None))
        del context.scene['widget_edit_armature']
        context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}


class POSE_OT_duplicate_and_edit_widget_of_selected_bones(
    POSE_OT_edit_widget_of_selected_bones
):
    """Duplicate, then edit custom shape of the selected bones"""

    bl_idname = "pose.duplicate_and_edit_widget_of_selected_bones"
    bl_label = "Duplicate & Edit Custom Shapes"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not cls.poll_without_linked_check(context):
            return False
        return True

    def execute(self, context):
        new_shapes = {}
        for pb in context.selected_pose_bones:
            if not pb.custom_shape:
                continue
            shape = pb.custom_shape
            if shape.name in new_shapes:
                pb.custom_shape = new_shapes[shape.name]
                continue
            new_shape = shape.copy()
            new_shape.make_local()
            new_shape.data = new_shape.data.copy()
            new_shape.asset_clear()
            new_shape.name = "WGT-" + pb.name

            for coll in shape.users_collection:
                coll.objects.link(new_shape)

            new_shapes[shape.name] = new_shape
            pb.custom_shape = new_shape
        return super().execute(context)


class POSE_OT_assign_selected_object_as_custom_shape(Operator):
    """Assign selected mesh object to all selected bones"""

    bl_idname = "pose.assign_selected_object_as_custom_shape"
    bl_label = "Assign Selected Object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'POSE':
            cls.poll_message_set("Must be in pose mode.")
            return False
        if len(context.selected_pose_bones) == 0:
            cls.poll_message_set("Must have selected pose bones.")
            return False
        if len([o for o in context.selected_objects if o.type == 'MESH']) != 1:
            cls.poll_message_set("Exactly one mesh object must be selected.")
            return False
        return True

    def execute(self, context):
        shape = [o for o in context.selected_objects if o.type == 'MESH'][0]
        counter = 0
        for pb in context.selected_pose_bones:
            if pb.custom_shape != shape:
                pb.custom_shape = shape
                counter += 1

        self.report({'INFO'}, f"{shape.name} assigned to bones: {counter}.")
        return {'FINISHED'}


class POSE_OT_edit_bone_display_props(Operator, bpy.types.BONE_PT_display):
    """Edit bone display properties. Like with any Blender property, you can hold Alt while dragging, to affect all selected bones"""

    bl_idname = "pose.edit_bone_display_props"
    bl_label = "Edit Bone Display Properties"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not context.active_pose_bone:
            cls.poll_message_set("No active bone.")
            return False
        return True

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=400)

    def draw(self, context):
        # TODO: This UI should work in Pose/Edit/WP mode and be upstreamed to BONE_PT_display_custom_shape.
        layout = self.layout.column()
        layout.use_property_decorate = False
        layout.use_property_split = True
        pbone = context.active_pose_bone
        bone = pbone.bone

        if not (pbone and bone):
            return

        self.draw_bone_color_settings(layout, pbone)
        layout.separator()
        self.draw_bone_shape_settings(layout, pbone)

    def draw_bone_color_settings(self, layout, pbone):
        layout.separator()
        row = layout.row(align=True)
        row.prop(pbone.bone.color, "palette", text="Bone Color")
        props = row.operator("armature.copy_bone_color_to_selected", text="", icon='UV_SYNC_SELECT')
        props.bone_type = 'EDIT'
        self.draw_bone_color_ui(layout, pbone.bone.color)

        row = layout.row(align=True)
        row.prop(pbone.color, "palette", text="Pose Bone Color")
        props = row.operator("armature.copy_bone_color_to_selected", text="", icon='UV_SYNC_SELECT')
        props.bone_type = 'POSE'
        self.draw_bone_color_ui(layout, pbone.color)

    def draw_bone_shape_settings(self, layout, pbone):
        layout.prop(pbone, "custom_shape", text="Custom Shape Object")

        if not pbone.custom_shape:
            layout.prop(pbone.bone, "display_type", text="Display As")
            return

        layout.prop_search(pbone, "custom_shape_transform", pbone.id_data.pose, "bones", text="Override Transform")
        if pbone.custom_shape.type != 'MESH' or len(pbone.custom_shape.data.polygons) > 0:
            layout.prop(pbone.bone, "show_wire", text="Force Wireframe")

        layout.prop(pbone, "custom_shape_translation", text="Translation")
        layout.prop(pbone, "custom_shape_rotation_euler", text="Rotation")
        layout.prop(pbone, "custom_shape_scale_xyz", text="Scale")

        length = pbone.bone.length
        layout.prop(pbone, "use_custom_shape_bone_size", text=f"Scale to Bone Length (x{length:.2f})")
        layout.separator()

        layout.prop(pbone, "custom_shape_wire_width")

    def execute(self, context):
        return {'FINISHED'}


class CLOUDRIG_MT_PIE_edit_custom_shape(Menu):
    bl_label = "Edit Custom Shape"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        plural = "s" if len(context.selected_pose_bones) > 1 else ""

        # 1) < Unassign Widget.
        pie.operator(POSE_OT_unassign_custom_shape.bl_idname, icon='X', text=f"Unassign Custom Shape{plural}")

        # 2) > Assign Widget from list.
        pie.operator(
            POSE_OT_assign_selected_custom_shape.bl_idname, icon='MESH_UVSPHERE'
        )

        # 3) v Reload Widget? (If it's in Widgets.blend).
        pie.operator(
            POSE_OT_reload_selected_custom_shape.bl_idname, icon='FILE_REFRESH', text=f"Reload Shape{plural}"
        )

        # 4) ^ Copy Widget to Selected.
        pie.operator(
            POSE_OT_copy_custom_shape_to_selected_bones.bl_idname, icon='COPYDOWN'
        )

        # 5) <^ Edit Custom Shape Transforms.
        pie.operator(POSE_OT_edit_bone_display_props.bl_idname, icon='PROPERTIES', text="Edit Properties")

        # 6) ^> Duplicate & Edit Widget.
        pie.operator(
            POSE_OT_duplicate_and_edit_widget_of_selected_bones.bl_idname, text=f"Duplicate & Edit Shape{plural}",
            icon='DUPLICATE',
        )

        # 7) <v Assign selected object as widget (if there's only 1 mesh selected)
        pie.operator(
            POSE_OT_assign_selected_object_as_custom_shape.bl_idname, icon='OBJECT_DATA'
        )

        # 8) v> Edit Widget (if ob isn't linked).
        pie.operator(
            POSE_OT_edit_widget_of_selected_bones.bl_idname, icon='GREASEPENCIL', text=f"Edit Shape{plural}"
        )


registry = [
    POSE_OT_unassign_custom_shape,
    POSE_OT_assign_selected_custom_shape,
    POSE_OT_reload_selected_custom_shape,
    POSE_OT_copy_custom_shape_to_selected_bones,
    POSE_OT_duplicate_and_edit_widget_of_selected_bones,
    POSE_OT_edit_widget_of_selected_bones,
    MESH_OT_return_to_pose_mode,
    POSE_OT_assign_selected_object_as_custom_shape,
    POSE_OT_edit_bone_display_props,
    CLOUDRIG_MT_PIE_edit_custom_shape,
]


def register():
    for keymap_name in ('Pose', 'Weight Paint'):
        register_hotkey(
            'wm.call_menu_pie',
            hotkey_kwargs={'type': "E", 'value': "PRESS", 'alt': True, 'ctrl': True},
            keymap_name=keymap_name,
            op_kwargs={'name': 'CLOUDRIG_MT_PIE_edit_custom_shape'},
        )

    register_hotkey(
        'mesh.return_to_pose_mode',
        hotkey_kwargs={'type': "E", 'value': "PRESS", 'alt': True, 'ctrl': True},
        keymap_name="Mesh",
    )
