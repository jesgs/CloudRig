import bpy, os
from bpy.types import Object, PoseBone
from mathutils import Vector, Euler
from bpy.types import Operator

from ...bs_utils.prefs import get_addon_prefs

CLOUDRIG_WIDGETS: list[str] = []
EXTERNAL_WIDGETS: list[str] = []

def ensure_widget(wgt_name, overwrite=True, clear_asset=True) -> Object | None:
    """Ensure a custom shapes exists:
    1. If the widget is in the current .blend file already, return it (unless we want to overwrite or link)
    2. Try to append/link it from the external .blend the user may have specified in the preferences.
    3. If that fails, try to append/link it from the Widgets.blend that ships with the add-on.
    """

    get_widgets_enum_items()

    if not wgt_name.startswith("WGT-"):
        wgt_name = "WGT-" + wgt_name

    prefs = get_addon_prefs()
    if not prefs: 
        return
    prefer_linked = prefs.widget_import_method == 'LINK'
    lib_abs_path = ""
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

    old_wgt_ob = bpy.data.objects.get(wgt_name)
    if old_wgt_ob:
        if not overwrite:
            # Object exists and we don't want to overwrite it, so just return it.
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
            # We failed to import matching widget, AND we didn't find one locally... So, we are sad.
            if " " in wgt_name:
                # Last resort: Try replacing space with underscore, and try again.
                return ensure_widget(wgt_name.replace(" ", "_"), overwrite=overwrite, clear_asset=clear_asset)
            else:
                raise ValueError(f"Widget not found: '{wgt_name}' '{lib_rel_path}'")
        return old_wgt_ob

    # Append/Link widget object from .blend
    with bpy.data.libraries.load(lib_rel_path, link=prefer_linked, relative=relative) as (
        data_from,
        data_to,
    ):
        for obj in data_from.objects:
            if obj == wgt_name:
                data_to.objects.append(obj)
                break

    new_wgt_ob = bpy.data.objects.get((wgt_name, lib_rel_path if prefer_linked else None))
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

    if clear_asset and new_wgt_ob and new_wgt_ob.library == None:
        new_wgt_ob.asset_clear()

    return new_wgt_ob

def get_native_widgets_path() -> str:
    return os.path.realpath(__file__).replace("widgets.py", "Widgets.blend")

def refresh_cloudrig_widgets() -> list[str]:
    """Build a list of custom shapes found in the Widgets.blend that ships with CloudRig.
    This should only be refreshed on Blender restart or Reload Scripts, otherwise it's unnecessary.
    """

    global CLOUDRIG_WIDGETS
    CLOUDRIG_WIDGETS = get_widget_obnames_of_blend(get_native_widgets_path())

def refresh_external_widgets(context=None):
    """Build a list of custom shapes found in the .blend that the user may or may not have browsed in the preferences.
    This should only be refreshed when that filepath changes, or on operators like Generate/Assign Custom Shape.
    """
    global EXTERNAL_WIDGETS
    prefs = get_addon_prefs(context)
    if not prefs:
        return []
    if prefs.widget_library == get_native_widgets_path():
        # If the user has CloudRig's native .blend browsed in the preferences, ignore it.
        return []
    EXTERNAL_WIDGETS = get_widget_obnames_of_blend(prefs.widget_library)

def get_widget_obnames_of_blend(blend_path: str) -> list[str]:
    if not (os.path.exists(blend_path) and os.path.isfile(blend_path)):
        return []

    wgt_ob_names: list[str] = []
    try:
        with bpy.data.libraries.load(blend_path) as (data_from, data_to):
            for obj in data_from.objects:
                if obj.startswith("WGT-"):
                    wgt_ob_names.append(obj)
    except Exception as exc:
        print(exc)

    return wgt_ob_names

def get_local_widgets() -> list[str]:
    return [obj.name for obj in bpy.data.objects if obj.name.startswith("WGT-")]

def get_widgets_enum_items(_scene=None, _context=None) -> list[tuple[str, str, str, str, int]] | None:
    """This is the `items` callback function for a widget selector EnumProperty.
    Widgets local to this .blend shall mask widgets found in the .blend provided by the user.
    And widgets found in the .blend provided by the user shall mask widgets found in the Widgets.blend that ships with the add-on.
    """
    global CLOUDRIG_WIDGETS
    global EXTERNAL_WIDGETS
    # First time this is called, populate the widget lists.
    if CLOUDRIG_WIDGETS == []:
        refresh_cloudrig_widgets()
    if EXTERNAL_WIDGETS == []:
        refresh_external_widgets()

    local_widgets = get_local_widgets()

    enum_items: list[tuple[str, str, str]] = []
    counter = 0
    used_names = []
    for wgt_names, type, icon in zip((local_widgets, EXTERNAL_WIDGETS, CLOUDRIG_WIDGETS), ("Local", "User", "CloudRig"), ("FILE_BLEND", "USER", "MOD_FLUID")):
        for wgt_name in wgt_names:
            counter += 1
            ui_name = wgt_name.replace("WGT-", "").replace("_", " ")
            if ui_name in used_names:
                # For name overlaps, priority is local > external > cloudrig.
                # Duplicate widget names across these 3 widget sources are not allowed.
                continue
            used_names.append(ui_name)
            enum_items.append((wgt_name, ui_name, ui_name, icon, counter))
        enum_items.append(None)

    return enum_items

def get_nonlocal_widgets():
    return CLOUDRIG_WIDGETS + EXTERNAL_WIDGETS

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
    if use_custom_shape_bone_size != None:
        pose_bone.use_custom_shape_bone_size = use_custom_shape_bone_size
    if show_wire != None:
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
    """Refresh widget selector list"""

    bl_idname = "pose.cloudrig_refresh_widget_list"
    bl_label = "Refresh Widget List"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        get_addon_prefs(context).update_widget_names(context)
        return {'FINISHED'}


registry = [CLOUDRIG_OT_refresh_widget_list]