import bpy, os
from bpy.types import Object

from ...bs_utils.prefs import get_addon_prefs

LIBRARY_WIDGETS = []

def ensure_widget(wgt_name, overwrite=True, clear_asset=True) -> Object:
    """Load custom shapes by appending them from Widgets.blend, unless they already exist in this file."""
    prefs = get_addon_prefs()
    link = prefs.widget_import_method == 'LINK'
    abs_path = prefs.widget_library
    relative = False
    try:
        rel_path = bpy.path.relpath(abs_path)
        relative = bpy.data.is_saved
        if not relative:
            rel_path = abs_path
    except ValueError:
        # This can happen when the widgets.blend is on a different drive.
        # In this case, I would argue that the abs_path is the rel_path.
        rel_path = abs_path
    assert os.path.exists(abs_path), (
        "Widgets.blend file not found: " + prefs.widget_library
    )
    # Check if it already exists locally.
    if not wgt_name.startswith("WGT-"):
        wgt_name = "WGT-" + wgt_name
    # We deliberately don't check for the library here, because sometimes we may
    # want to overwrite a local widget with a linked one.
    old_wgt_ob = bpy.data.objects.get(wgt_name)
    if old_wgt_ob:
        if overwrite:
            if old_wgt_ob.library:
                if link:
                    if old_wgt_ob.library.filepath in {abs_path, rel_path}:
                        # If object is already linked from the target lib, no need to do it again.
                        return old_wgt_ob
                else:
                    # The object is already linked from the target lib, but the caller wants it to be local instead.
                    old_wgt_ob.make_local()
                    if old_wgt_ob.data:
                        old_wgt_ob.data.make_local()
                    if clear_asset:
                        old_wgt_ob.asset_clear()
                    return old_wgt_ob
            else:
                old_wgt_ob.name = old_wgt_ob.name + "_temp"
                if old_wgt_ob.data:
                    old_wgt_ob.data.name = old_wgt_ob.data.name + "_temp"
        else:
            # Object exists and we don't want to overwrite it, so just return it.
            return old_wgt_ob

    # Import widget object from Widgets.blend file.
    with bpy.data.libraries.load(rel_path, link=link, relative=relative) as (
        data_from,
        data_to,
    ):
        for o in data_from.objects:
            if o == wgt_name:
                data_to.objects.append(o)

    new_wgt_ob = bpy.data.objects.get((wgt_name, rel_path if link else None))
    if not new_wgt_ob:
        if old_wgt_ob:
            # We failed to import a widget with the provided name.
            # So, let's just return the old one, whether it's linked or not.
            old_wgt_ob.name = wgt_name
            if old_wgt_ob.data:
                old_wgt_ob.data.name = wgt_name
            return old_wgt_ob
        else:
            # We failed to import anything, AND we didn't have anything... So, we are sad.
            raise ValueError(f"Widget not found: '{wgt_name}' '{rel_path}'")
    elif new_wgt_ob == old_wgt_ob:
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


def init_widget_list():
    """Build a list of available custom shapes by checking inside Widgets.blend."""

    global LIBRARY_WIDGETS
    LIBRARY_WIDGETS = []

    prefs = get_addon_prefs()
    if not prefs:
        return
    blend_path = prefs.widget_library

    if not os.path.exists(blend_path) and os.path.isfile(blend_path):
        # User customized the widget path to a non-existent one.
        # We do not fall back to default, because we want to make sure user notices that something is wrong.
        return

    try:
        with bpy.data.libraries.load(blend_path) as (data_from, data_to):
            for o in data_from.objects:
                if o.startswith("WGT-"):
                    ui_name = o.replace("WGT-", "").replace("_", " ")
                    LIBRARY_WIDGETS.append((o, ui_name, ui_name))
    except Exception as exc:
        print(exc)

    return LIBRARY_WIDGETS


def get_widgets_enum_items(_scene=None, _context=None) -> list[str, str, str] | None:
    """This is needed because bpy.props.EnumProperty.items needs to be a dynamic list,
    which it can only be with a function callback."""
    global LIBRARY_WIDGETS

    # First time this is called, populate the widget list.
    if LIBRARY_WIDGETS == []:
        init_widget_list()

    enum_items = LIBRARY_WIDGETS[:]
    enum_items.append(None)
    try:
        for o in bpy.data.objects:
            if o.name.startswith("WGT"):
                ui_name = o.name.replace("WGT-", "").replace("_", " ")
                item = (o.name, ui_name, ui_name)
                if item not in enum_items:
                    enum_items.append(item)
    except AttributeError:
        return

    return enum_items

def get_widget_index(wgt_name: str) -> int:
    enum_items = get_widgets_enum_items()
    if not enum_items:
        return 0
    for i, (identifier, name, description) in enumerate():
        if name == wgt_name:
            return i
