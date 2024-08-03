from ..utils.misc import check_addon
from bpy.types import Object

try:
    # pre-4.2
    from bone_selection_sets import from_json
    from bone_selection_sets import to_json
except ModuleNotFoundError:
    # post-4.2
    from bl_operators.bone_selection_sets import _from_json as from_json
    from bl_operators.bone_selection_sets import _to_json as to_json


def check(context, arm_obj: Object):
    """Check if an armature might be using Selection Sets.
    Need to check in two ways, first for pre-4.2, then post-4.2, when
    Selection Sets became built-in.
    """
    return check_addon(context, 'bone_selection_sets') or hasattr(
        arm_obj, 'selection_sets'
    )


def wipe(arm_obj: Object):
    """Remove all Selection Sets."""
    if 'selection_sets' in arm_obj:
        # Pre-4.2
        del arm_obj['selection_sets']
    if hasattr(arm_obj, 'selection_sets'):
        # Post-4.2
        arm_obj.selection_sets.clear()


def store(context, arm_obj: Object) -> dict:
    for selset in arm_obj.selection_sets:
        selset.is_selected = True

    active_bkp = context.view_layer.objects.active
    context.view_layer.objects.active = arm_obj
    sel_sets = to_json(context)

    context.view_layer.objects.active = active_bkp

    return sel_sets


def load(context, arm_obj: Object, sel_sets: dict):
    active_bkp = context.view_layer.objects.active
    context.view_layer.objects.active = arm_obj
    from_json(context, sel_sets)
    context.view_layer.objects.active = active_bkp
