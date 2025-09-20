from bpy.types import Object

from bl_operators.bone_selection_sets import _from_json as from_json
from bl_operators.bone_selection_sets import _to_json as to_json


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
