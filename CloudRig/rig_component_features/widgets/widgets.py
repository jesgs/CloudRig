import os
from pathlib import Path

import bpy
from bpy.types import ImagePreview, Object, Operator, PoseBone
from mathutils import Euler, Vector

from ...bs_utils.prefs import get_addon_prefs
from ...icons import ensure_icon

CLOUDRIG_WIDGETS: dict[str, ImagePreview] = {}
EXTERNAL_WIDGETS: dict[str, ImagePreview] = {}
LOCAL_WIDGETS: dict[str, ImagePreview] = {}

def ensure_widget(wgt_name, overwrite=True, clear_asset=True) -> Object | None:
    """Ensure a custom shapes exists:
    1. If the widget is in the current .blend file already, return it (unless we want to overwrite or link)
    2. Try to append/link it from the external .blend the user may have specified in the preferences.
    3. If that fails, try to append/link it from the Widgets.blend that ships with the add-on.
    """

    refresh_widget_list()

    wgt_obj_name = wgt_name
    if not wgt_obj_name.startswith("WGT-"):
        wgt_obj_name = "WGT-" + wgt_name

    prefs = get_addon_prefs()
    if not prefs:
        return
    prefer_linked = prefs.widget_import_method == 'LINK'
    lib_abs_path = lib_rel_path = ""
    if wgt_name in EXTERNAL_WIDGETS:
        lib_abs_path = prefs.widget_library
    elif wgt_name in CLOUDRIG_WIDGETS:
        lib_abs_path = get_native_widgets_path()
    if lib_abs_path:
        relative = False
        try:
            lib_rel_path = bpy.path.relpath(lib_abs_path)
            relative = bpy.data.is_saved
            if not relative:
                lib_rel_path = lib_abs_path
        except ValueError:
            # This can happen when the widgets.blend is on a different drive.
            # In this case, I would argue that the abs_path is the rel_path.
            lib_rel_path = lib_abs_path
        assert os.path.exists(lib_abs_path), f"Widgets.blend file not found: {lib_abs_path}"

    old_wgt_ob = bpy.data.objects.get(wgt_obj_name)
    if old_wgt_ob:
        if not overwrite or not lib_abs_path:
            # Object exists and we either don't want to overwrite it, or it's not in any library to overwrite it from.
            return old_wgt_ob
        if old_wgt_ob.library:
            if prefer_linked:
                if old_wgt_ob.library.filepath in {lib_abs_path, lib_rel_path}:
                    # If object is already linked from the target lib, no need to do it again.
                    return old_wgt_ob
            else:
                # The object is already linked from somewhere, but the caller wants it to be local instead.
                old_wgt_ob.make_local()
                if old_wgt_ob.data:
                    old_wgt_ob.data.make_local()
                if clear_asset:
                    old_wgt_ob.asset_clear()
                return old_wgt_ob
        else:
            # Local object exists, but we want to overwrite it. Prepare it for deletion.
            old_wgt_ob.name = old_wgt_ob.name + "_temp"
            if old_wgt_ob.data:
                old_wgt_ob.data.name = old_wgt_ob.data.name + "_temp"

    if not lib_abs_path:
        if not old_wgt_ob:
            # Widget wasn't found in any of our lists, AND we didn't find one locally... So, we are sad.
            raise ValueError(f"Widget not found: '{wgt_name}' '{lib_abs_path or lib_rel_path}'")
        return old_wgt_ob

    # Append/Link widget object from .blend
    with bpy.data.libraries.load(lib_rel_path, link=prefer_linked, relative=relative) as (
        data_from,
        data_to,
    ):
        for obj_name in data_from.objects:
            if obj_name == wgt_obj_name:
                data_to.objects.append(obj_name)
                break

    new_wgt_ob = bpy.data.objects.get((wgt_obj_name, lib_rel_path if prefer_linked else None))
    assert new_wgt_ob, f"Widget failed to import {wgt_name} from {lib_rel_path}"

    if new_wgt_ob == old_wgt_ob:
        return old_wgt_ob
    elif old_wgt_ob and overwrite:
        # Widget already existed, but we want to overwrite it with what we just imported.
        old_wgt_ob.user_remap(new_wgt_ob)
        if old_wgt_ob.data and old_wgt_ob.type == 'MESH':
            bpy.data.meshes.remove(old_wgt_ob.data)
        else:
            bpy.data.objects.remove(old_wgt_ob)

    if clear_asset and new_wgt_ob and new_wgt_ob.library is None:
        new_wgt_ob.asset_clear()

    return new_wgt_ob

def get_native_widgets_path() -> str:
    return os.path.realpath(__file__).replace("widgets.py", "Widgets.blend")

def get_wgt_names_in_blend(blend_path: str) -> list[str]:
    if blend_path == bpy.data.filepath:
        wgt_names = [widget_name(o.name) for o in bpy.data.objects if o.name.startswith("WGT-")]
        return wgt_names

    if not (os.path.exists(blend_path) and os.path.isfile(blend_path)):
        return []

    wgt_names: list[str] = []
    try:
        with bpy.data.libraries.load(blend_path) as (data_from, data_to):
            for obj_name in data_from.objects:
                if obj_name.startswith("WGT-"):
                    wgt_names.append(widget_name(obj_name))
    except Exception as exc:
        print(exc)

    return wgt_names

def load_widgets_of_blend(blend_path: str) -> dict[str, ImagePreview]:
    thumb_dir = Path(blend_path).parent / Path("thumbnails")
    wgt_names = get_wgt_names_in_blend(blend_path)
    icons = {}
    for wgt_name in wgt_names:
        icons[wgt_name] = ensure_icon(wgt_name.replace("WGT-", ""), dir_path=thumb_dir, icon_map_name="Widget Thumbnails")

    return icons

def widget_name(name: str) -> str:
    return name.replace("WGT-", "")

def refresh_cloudrig_widgets():
    """Build a list of custom shapes found in the Widgets.blend that ships with CloudRig.
    This should only be refreshed on Blender restart or Reload Scripts, otherwise it's unnecessary.
    """

    global CLOUDRIG_WIDGETS
    wgt_blend_path = get_native_widgets_path()
    CLOUDRIG_WIDGETS = load_widgets_of_blend(wgt_blend_path)

def refresh_external_widgets(context=None):
    """Build a list of custom shapes found in the .blend that the user may or may not have browsed in the preferences.
    This should only be refreshed when that filepath changes, or on operators like Generate/Assign Custom Shape.
    """
    global EXTERNAL_WIDGETS
    prefs = get_addon_prefs(context)
    if not prefs or not prefs.widget_library or not os.path.isfile(prefs.widget_library):
        return []
    wgt_blend_path = prefs.widget_library
    if wgt_blend_path == get_native_widgets_path():
        # If the user has CloudRig's native .blend browsed in the preferences, ignore it.
        return []
    EXTERNAL_WIDGETS = load_widgets_of_blend(wgt_blend_path)

def refresh_local_widgets():
    global LOCAL_WIDGETS
    LOCAL_WIDGETS = load_widgets_of_blend(bpy.data.filepath)

def refresh_widget_list(force_cloudrig=False, force_external=False):
    """This is the `items` callback function for a widget selector EnumProperty.
    Widgets local to this .blend shall mask widgets found in the .blend provided by the user.
    And widgets found in the .blend provided by the user shall mask widgets found in the Widgets.blend that ships with the add-on.
    """
    global CLOUDRIG_WIDGETS
    global EXTERNAL_WIDGETS
    global LOCAL_WIDGETS

    # First time this is called (per script reload), populate the widget lists.
    if EXTERNAL_WIDGETS == {} or force_external:
        refresh_external_widgets()
    if CLOUDRIG_WIDGETS == {} or force_cloudrig:
        refresh_cloudrig_widgets()

    refresh_local_widgets()

    all_widgets = CLOUDRIG_WIDGETS.copy()
    all_widgets.update(EXTERNAL_WIDGETS)
    all_widgets.update(LOCAL_WIDGETS)

    prefs = get_addon_prefs()
    prefs.widget_names.clear()
    used_names = set()
    for wgt_name, icon in all_widgets.items():
        ui_name = wgt_name.replace("WGT-", "").replace("_", " ")
        if ui_name in used_names:
            # For name overlaps, priority is local > external > cloudrig.
            # Duplicate widget names across these 3 widget sources are not allowed.
            continue
        used_names.add(ui_name)

        widget_entry = prefs.widget_names.add()
        widget_entry.name = ui_name

    return all_widgets

def widgets_enum_items(_operator=None, context=None) -> list[tuple[str, str, str, str, int]]:
    enum_items: list[tuple[str, str, str]] = []

    all_widgets = CLOUDRIG_WIDGETS.copy()
    all_widgets.update(EXTERNAL_WIDGETS)
    all_widgets.update(LOCAL_WIDGETS)

    for i, (name, icon) in enumerate(sorted(all_widgets.items(), key=lambda w: w[0])):
        enum_items.append((name, name, name, icon.icon_id, i))

    return enum_items

def get_nonlocal_widgets():
    ret = CLOUDRIG_WIDGETS.copy()
    ret.update(EXTERNAL_WIDGETS)
    return ret

def get_pbone_custom_shape_data(pose_bone: PoseBone) -> dict[str]:
    """
    Saves all custom shape properties of a pose bone.
    Returns a dictionary with the object and its settings.
    """
    return {
        "custom_shape": pose_bone.custom_shape,
        "custom_shape_scale_xyz": pose_bone.custom_shape_scale_xyz.copy(),
        "custom_shape_translation": pose_bone.custom_shape_translation.copy(),
        "custom_shape_rotation_euler": pose_bone.custom_shape_rotation_euler.copy(),
        "use_custom_shape_bone_size": pose_bone.use_custom_shape_bone_size,
        "custom_shape_wire_width": pose_bone.custom_shape_wire_width,
        "show_wire": pose_bone.bone.show_wire,
    }

def set_pbone_custom_shape_data(
        pose_bone: PoseBone,
        custom_shape: Object = None,
        custom_shape_translation: Vector = None,
        custom_shape_rotation_euler: Euler = None,
        custom_shape_scale_xyz: Vector = None,
        use_custom_shape_bone_size: bool = None,
        show_wire: bool = None,
        custom_shape_wire_width: float = None,
        ):
    """Applies the passed custom shape settings to the pose bone."""
    if custom_shape:
        pose_bone.custom_shape = custom_shape
    if custom_shape_translation:
        pose_bone.custom_shape_translation = custom_shape_translation
    if custom_shape_rotation_euler:
        pose_bone.custom_shape_rotation_euler = custom_shape_rotation_euler
    if custom_shape_scale_xyz:
        pose_bone.custom_shape_scale_xyz = custom_shape_scale_xyz
    if use_custom_shape_bone_size is not None:
        pose_bone.use_custom_shape_bone_size = use_custom_shape_bone_size
    if show_wire is not None:
        pose_bone.bone.show_wire = show_wire
    if custom_shape_wire_width:
        pose_bone.custom_shape_wire_width = custom_shape_wire_width

def get_custom_shape_rig_data(rig: Object) -> dict[str, dict]:
    return {
        pb.name: get_pbone_custom_shape_data(pb)
        for pb in rig.pose.bones
    }

def apply_custom_shape_rig_data(rig: Object, custom_shape_data: dict) -> None:
    if not (rig and rig.pose):
        return
    for pb in rig.pose.bones:
        if pb.name in custom_shape_data:
            set_pbone_custom_shape_data(
                pb,
                **custom_shape_data[pb.name],
            )


class CLOUDRIG_OT_refresh_widget_list(Operator):
    """The widget list can't be fully dynamic, so if you're not seeing a widget that should show up, click this."""

    bl_idname = "pose.cloudrig_refresh_widget_list"
    bl_label = "Refresh Widget List"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        refresh_widget_list(force_cloudrig=True, force_external=True)
        self.report({'INFO'}, 'Refreshed all widgets and icons.')
        return {'FINISHED'}


registry = [CLOUDRIG_OT_refresh_widget_list]
