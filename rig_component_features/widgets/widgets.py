import bpy
import os
from ...utils.misc import get_addon_prefs


def ensure_widget(wgt_name, overwrite=True, clear_asset=True):
    """Load custom shapes by appending them from Widgets.blend, unless they already exist in this file."""
    prefs = get_addon_prefs()
    link = prefs.widget_import_method == 'LINK'
    blend_path = prefs.widget_library
    try:
        rel_path = bpy.path.relpath(blend_path)
    except ValueError:
        # This can happen when the widgets.blend is on a different drive.
        rel_path = blend_path
    assert os.path.exists(blend_path), (
        "Widgets.blend file not found: " + prefs.widget_library
    )
    # Check if it already exists locally.
    if not wgt_name.startswith("WGT-"):
        wgt_name = "WGT-" + wgt_name
    # We deliberately don't check for the library here, because sometimes we may
    # want to overwrite a local widget with a linked one.
    wgt_ob = bpy.data.objects.get(wgt_name)
    if wgt_ob:
        if overwrite:
            if wgt_ob.library:
                if link:
                    if wgt_ob.library.filepath in {blend_path, rel_path}:
                        # If object is already linked from the target lib, no need to do it again.
                        return wgt_ob
                else:
                    # The object is already linked from the target lib, but the caller wants it to be local instead.
                    wgt_ob.make_local()
                    wgt_ob.data.make_local()
                    if clear_asset:
                        wgt_ob.asset_clear()
                    return wgt_ob
            else:
                wgt_ob.name = wgt_ob.name + "_temp"
                wgt_ob.data.name = wgt_ob.data.name + "_temp"
        else:
            # Object exists and we don't want to overwrite it, so just return it.
            return wgt_ob

    # Import widget object from Widgets.blend file.
    relative = False
    if bpy.data.is_saved:
        relative = True
        blend_path = bpy.path.relpath(blend_path)
    with bpy.data.libraries.load(blend_path, link=link, relative=relative) as (
        data_from,
        data_to,
    ):
        for o in data_from.objects:
            if o == wgt_name:
                data_to.objects.append(o)

    new_wgt_ob = bpy.data.objects.get((wgt_name, blend_path if link else None))
    if not new_wgt_ob:
        if wgt_ob:
            # We failed to import a widget with the provided name, but a local one already exists.
            # So, let's just return that local one, whether it's linked or not.
            wgt_ob.name = wgt_name
            wgt_ob.data.name = wgt_name
            return wgt_ob
        else:
            # We failed to import anything, AND we didn't have anything... So, we are sad.
            return None
    elif new_wgt_ob == wgt_ob:
        return wgt_ob
    elif wgt_ob and overwrite:
        # Widget already existed, but we want to overwrite it with what we just imported.
        wgt_ob.user_remap(new_wgt_ob)

    wgt_ob = new_wgt_ob

    if clear_asset and wgt_ob and wgt_ob.library == None:
        wgt_ob.asset_clear()

    return wgt_ob
