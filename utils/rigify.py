from rigify import rig_lists

def find_rig_class(rig_type):
    rig_module = rig_lists.rigs[rig_type]["module"]

    return rig_module.Rig