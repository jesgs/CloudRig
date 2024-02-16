import os
import bpy
from mathutils import Matrix
from bpy.props import BoolProperty, StringProperty, EnumProperty

from ..rig_component_features.object import EnsureVisible
from ..rig_component_features.widgets.widgets import ensure_widget

widgets_visible = []
widget_items = []


def restore_all_widgets_visibility():
    global widgets_visible

    if widgets_visible != []:
        for w in widgets_visible[:]:
            try:
                w.restore()
            except:
                pass
    widgets_visible = []


def assign_to_collection(obj, collection):
    if not collection:
        return
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def get_widget_blend_path() -> str:
    filedir = os.path.dirname(os.path.realpath(__file__))
    blend_path = os.sep.join(
        filedir.split(os.sep)[:-1]
        + ['rig_component_features', 'widgets', 'Widgets.blend']
    )
    return blend_path


def get_widget_list(self, context):
    """This is needed because bpy.props.EnumProperty.items needs to be a dynamic list,
    which it can only be with a function callback."""
    global widget_items

    local_widgets = []
    for o in bpy.data.objects:
        if o.name.startswith("WGT"):
            ui_name = o.name.replace("WGT-", "").replace("_", " ")
            item = (o.name, ui_name, ui_name)
            local_widgets.append(item)

            for existing in widget_items:
                if existing == item:
                    widget_items.remove(existing)
                    break

    local_widgets.append(None)

    local_widgets.extend(widget_items)

    return local_widgets


def refresh_widget_list():
    """Build a list of available custom shapes by checking inside Widgets.blend."""

    global widget_items
    widget_items = []

    with bpy.data.libraries.load(get_widget_blend_path()) as (data_from, data_to):
        for o in data_from.objects:
            if o.startswith("WGT-"):
                ui_name = o.replace("WGT-", "").replace("_", " ")
                widget_items.append((o, ui_name, ui_name))

    return widget_items


def transform_widget_to_bone(pb: bpy.types.PoseBone, select=False):
    """Transform a pose bone's custom shape object to match the bone's visual transforms."""
    shape = pb.custom_shape

    assert (
        shape
    ), "Error: No shape to edit."  # This function should only be called when the active bone has a custom shape!

    if select:
        shape.select_set(True)

    transform_bone = pb
    if pb.custom_shape_transform:
        transform_bone = pb.custom_shape_transform

    # Step 1: Account for additional scaling from use_custom_shape_bone_size,
    # which scales the shape by the bone length.
    scale = pb.custom_shape_scale_xyz.copy()
    if pb.use_custom_shape_bone_size:
        scale *= pb.bone.length

    # Step 2: Create a matrix from the custom shape translation, rotation
    # and this scale which already accounts for bone length.
    custom_shape_matrix = Matrix.LocRotScale(
        pb.custom_shape_translation, pb.custom_shape_rotation_euler, scale
    )

    # Step 3: Multiply the pose bone's world matrix by the custom shape matrix.
    final_matrix = transform_bone.matrix @ custom_shape_matrix

    # Step 4: Apply this matrix to the object.
    # It should now match perfectly with the visual transforms of the pose bone,
    # unless there is skew.
    shape.matrix_world = final_matrix


class POSE_OT_toggle_edit_widget(bpy.types.Operator):
    """Assign a widget to all selected bones, or start editing the widget of the active bone, if it is the only bone selected"""

    bl_idname = "pose.toggle_edit_widget"
    bl_label = "Assign Widget"
    bl_options = {'REGISTER', 'UNDO'}

    def update_name(self, context):
        if not self.use_custom_widget_name:
            self.widget_name = self.widget_shape
        else:
            # Use the active bone for the initial naming of the shape.
            self.widget_name = "WGT-" + context.active_pose_bone.name

    widget_name: StringProperty(name="Widget Name")
    use_custom_widget_name: BoolProperty(
        name="Custom Widget",
        description="Create a new widget object based on the selected shape, so you can modify it without affecting other bones that also use that shape",
        update=update_name,
    )
    widget_shape: EnumProperty(
        name="Widget Shape",
        description="Choose a widget shape from CloudRig's widget library as well as any objects in the current file prefixed with 'WGT-'",
        items=get_widget_list,
        update=update_name,
    )
    widget_op: EnumProperty(
        name="Operation",
        description="What to do with the widgets of the selected bones",
        items=[
            ('ASSIGN', 'Assign', 'Assign a shape to the selected bones'),
            ('CLEAR', 'Clear', 'Un-assign the shapes of the selected bones'),
        ],
    )

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            if context.scene.widget_edit_armature != "":
                return True

        pb = context.active_pose_bone
        return context.mode == 'POSE' and pb

    def invoke(self, context, event):
        refresh_widget_list()
        self.widget_shape = 'WGT-Cube'
        if context.mode == 'EDIT_MESH':
            return self.execute(context)

        if (
            len(context.selected_pose_bones) > 1
            or context.active_pose_bone.custom_shape == None
        ):
            self.update_name(context)
            wm = context.window_manager
            return wm.invoke_props_dialog(self)
        else:
            return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.row().prop(self, 'widget_op', expand=True)
        if self.widget_op == 'CLEAR':
            return

        # We want to put a textbox and a toggle button underneath an enum drop-down
        # in a way that they align, which is sadly an absolute nightmare.
        row1 = layout.row()
        split1 = row1.split(factor=0.4)
        split1.alignment = 'RIGHT'
        split1.label(text="Widget Shape")
        split1.prop(self, 'widget_shape', text="")

        row2 = layout.row()
        split2 = row2.split(factor=0.4)
        split2.alignment = 'RIGHT'
        split2.label(text="Widget Name")
        row = split2.row(align=True)
        sub1 = row.row()
        sub1.enabled = self.use_custom_widget_name
        sub1.prop(self, 'widget_name', text="")

        sub2 = row.row()
        sub2.prop(self, 'use_custom_widget_name', text="", icon='GREASEPENCIL')

    def assign_shape_to_selected_bones(self, context, widget_shape: str, ob_name=""):
        rig = context.active_object
        if (
            hasattr(rig.data, 'rigify_widgets_collection')
            and rig.data.rigify_widgets_collection
        ):
            # Rigify integration: If we're on a metarig, use the widget collection.
            collection = rig.data.rigify_widgets_collection
        elif hasattr(rig, 'cloudrig') and rig.cloudrig.generator.widget_collection:
            # CloudRig integration: If we're on a metarig, use the widget collection.
            collection = rig.cloudrig.generator.widget_collection
        else:
            collection = context.scene.collection
        shape = ensure_widget(widget_shape, collection=collection)

        if ob_name:
            shape = bpy.data.objects.new(
                name=ob_name, object_data=bpy.data.meshes.new_from_object(shape)
            )
            shape.data.name = ob_name
            collection.objects.link(shape)

        # Assign to all selected bones.
        for pb in context.selected_pose_bones:
            pb.custom_shape = shape

    def enter_shape_edit_mode_single(self, context):
        rig = context.active_object
        active_pb = context.active_pose_bone
        shape = active_pb.custom_shape

        assert (
            shape
        ), "Error: No shape to edit."  # This function should only be called when the active bone has a custom shape!

        # If active bone has a bone shape, reveal it.
        global widgets_visible
        widgets_visible.append(EnsureVisible(shape))

        # Enter mesh edit mode on the now visible bone shape.
        bpy.ops.object.mode_set(mode='OBJECT')

        context.scene.widget_edit_armature = rig.name
        context.view_layer.objects.active = shape
        bpy.ops.object.select_all(action='DESELECT')
        transform_widget_to_bone(active_pb, select=True)
        context.view_layer.update()

        bpy.ops.object.mode_set(mode='EDIT')

    def exit_shape_edit_mode(self, context):
        """Restore rig selection state and mode."""
        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = bpy.data.objects.get(
            context.scene.widget_edit_armature
        )
        context.scene.widget_edit_armature = ""
        bpy.ops.object.mode_set(mode='POSE')

        context.scene.is_widget_edit_mode = not context.scene.is_widget_edit_mode
        context.view_layer.update()

    def execute(self, context):
        restore_all_widgets_visibility()

        if self.widget_op == 'CLEAR':
            for pb in context.selected_pose_bones:
                pb.custom_shape = None
                pb.custom_shape_translation = (0, 0, 0)
                pb.custom_shape_rotation_euler = (0, 0, 0)
                pb.custom_shape_scale_xyz = (1, 1, 1)
            return {'FINISHED'}

        widget_name = ""
        if self.use_custom_widget_name:
            widget_name = self.widget_name

        if context.mode == 'POSE':
            if context.active_pose_bone not in context.selected_pose_bones:
                self.report(
                    {'ERROR'},
                    "Error: User intention unclear. Active bone must be selected.",
                )
                return {'CANCELLED'}

            if len(context.selected_pose_bones) == 1:
                if context.active_pose_bone.custom_shape:
                    self.enter_shape_edit_mode_single(context)
                else:
                    self.assign_shape_to_selected_bones(
                        context, self.widget_shape, widget_name
                    )
            else:
                self.assign_shape_to_selected_bones(
                    context, self.widget_shape, widget_name
                )

        elif context.mode == 'EDIT_MESH':
            self.exit_shape_edit_mode(context)

        return {'FINISHED'}


class POSE_OT_make_widget_unique(bpy.types.Operator):
    """Re-assign this bone's shape to a unique duplicate, so it can be edited without affecting other bones using the same widget"""

    bl_idname = "pose.make_widget_unique"
    bl_label = "Make Unique Duplicate of Widget"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(name="Object Name")

    @classmethod
    def poll(cls, context):
        pb = context.active_pose_bone
        return context.mode == 'POSE' and pb and pb.custom_shape

    def invoke(self, context, event):
        pb = context.active_pose_bone
        self.new_name = "WGT-" + pb.name

        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.row().prop(self, "new_name")

    def execute(self, context):
        pb = context.active_pose_bone
        shape = pb.custom_shape

        mesh = bpy.data.meshes.new_from_object(shape)
        mesh.name = self.new_name
        obj = bpy.data.objects.new(self.new_name, mesh)
        for c in shape.users_collection:
            c.objects.link(obj)

        pb.custom_shape = obj

        bpy.ops.pose.toggle_edit_widget()

        return {'FINISHED'}


class POSE_OT_assign_asset_as_widget(bpy.types.Operator):
    """Assign this asset as the custom shape for selected bones"""

    bl_idname = "pose.assign_asset_as_custom_shape"
    bl_label = "Assign Asset as Custom Shape"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    ob_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE'

    def execute(self, context):
        obj = bpy.data.objects.get(self.ob_name)
        assert obj, "TODO: Automatically append the widget before trying to apply it"

        for pb in context.selected_pose_bones:
            pb.custom_shape = obj
            # Reset any transform values
            pb.custom_shape_scale_xyz = [1, 1, 1]
            pb.custom_shape_translation = [0, 0, 0]
            pb.custom_shape_rotation_euler = [0, 0, 0]

        return {'FINISHED'}


def draw_asset_rightclick_menu(self, context):
    layout = self.layout
    ob = context.asset_file_handle.asset_data.id_data
    if (
        context.asset_file_handle.name.startswith("WGT-")
        and context.selected_pose_bones
    ):
        op = layout.operator(POSE_OT_assign_asset_as_widget.bl_idname)
        op.ob_name = context.asset_file_handle.name


def draw_button(self, context):
    layout = self.layout
    layout.operator(POSE_OT_toggle_edit_widget.bl_idname)
    layout.operator(POSE_OT_make_widget_unique.bl_idname)


registry = [
    POSE_OT_toggle_edit_widget,
    POSE_OT_make_widget_unique,
    POSE_OT_assign_asset_as_widget,
]


def register():
    bpy.types.ASSETBROWSER_MT_context_menu.append(draw_asset_rightclick_menu)

    bpy.types.VIEW3D_MT_pose.append(draw_button)
    bpy.types.Scene.is_widget_edit_mode = BoolProperty()
    bpy.types.Scene.widget_edit_armature = StringProperty()


def unregister():
    bpy.types.ASSETBROWSER_MT_context_menu.remove(draw_asset_rightclick_menu)

    bpy.types.VIEW3D_MT_pose.remove(draw_button)
    try:
        del bpy.types.Scene.is_widget_edit_mode
        del bpy.types.Scene.widget_edit_armature
    except AttributeError:
        pass
