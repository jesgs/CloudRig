import bpy
from bpy.types import Object, PoseBone, EditBone

def test_copy_mirror_component(context, scene_workflow):
    metarig = context.active_object
    bpy.ops.object.mode_set(mode='POSE')
    left_pbone = metarig.pose.bones['UpperArm.L']
    right_pbone = metarig.pose.bones['UpperArm.R']
    left_pbone.property_unset('cloudrig_component')
    select_pbone(right_pbone)
    bpy.ops.pose.cloudrig_symmetrize_components()
    left_pbone = metarig.pose.bones['UpperArm.L']
    assert left_pbone.cloudrig_component.component_type == 'Limb: Generic'
    assert left_pbone.cloudrig_component.params.parenting.parent_slots[3].bone == 'ROOT-UpperArm.L'

def test_symmetrize(context, scene_workflow):
    metarig = context.active_object
    bpy.ops.object.mode_set(mode='POSE')
    for pb in metarig.pose.bones:
        pb.select = pb.name.endswith(".L")
    assert bpy.ops.pose.symmetrize_rigging() == {'FINISHED'}
    # Test a couple of specifics...
    assert metarig.pose.bones['UpperArm.R'].cloudrig_component.params.parenting.parent_slots[3].bone == "ROOT-UpperArm.R", "Parenting settings didn't symmetrize."
    assert metarig.pose.bones['LipRing3.R'].constraints[1].name == 'Armature@ACT-MouthCorner.R', "Constraint name didn't symmetrize."
    assert metarig.pose.bones['LipRing3.R'].constraints[1].subtarget == 'ACT-MouthCorner.R', "Subtarget didn't symmetrize."
    # wtf, this is actually broken...!!!
    assert metarig.pose.bones['LipRing3.R'].constraints[0].targets[0].subtarget == 'ACT-MouthCorner.R', "Armature Constraint Subtarget didn't symmetrize."
    fc = metarig.animation_data.drivers.find('pose.bones["LipRing3.R"].constraints["Armature@ACT-MouthCorner.R"].influence')
    assert fc, "Driver didn't get symmetrized."
    assert fc.driver.variables[0].targets[0].bone_target == 'ACT-MouthCorner.R', "Driver variable target didn't get symmetrized."

def test_better_bone_extrude(context, scene_workflow):
    metarig = context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    my_bone = metarig.data.edit_bones['LipRing3.L']
    select_ebone(my_bone)
    metarig.data.use_mirror_x = True
    bpy.ops.armature.better_bone_duplicate()
    new_bone = context.active_bone
    assert new_bone.name == 'LipRing6.L', f"Bone name didn't increment correctly: {new_bone.name}"
    assert 'LipRing6.R' in metarig.data.edit_bones, "Mirror bone name didn't increment correctly"
    bpy.ops.armature.select_all(action='DESELECT')
    metarig.data.edit_bones['LipRing6.L'].select_tail = True
    bpy.ops.armature.better_bone_extrude()
    new_bone = context.active_bone
    assert new_bone.name == 'LipRing7.L', f"Bone name didn't increment correctly: {new_bone.name}"

def test_bone_parent_ops(context, scene_simple):
    rig = context.active_object
    rig.data.use_mirror_x = True
    def run_bone_parent_ops(mode):
        # Need to have the same state by the end of this function as at the start,
        # since we want to run it once for each mode supported by parneting operators.
        bones = rig.data.bones
        pbones = rig.pose.bones
        if mode=='EDIT':
            bones = rig.data.edit_bones
        select_bone(rig, 'Bone2.L')
        bpy.ops.pose.disconnect_selected()
        assert bones['Bone2.L'].use_connect is bones['Bone2.R'].use_connect is False, "Disconnect op didn't disconnect bones as expected."
        bpy.ops.pose.unparent_selected()
        assert bones['Bone2.L'].parent is bones['Bone2.R'].parent is None, "Unparent op didn't unparent bones as expected."
        select_bone(rig, 'Bone1.L', expand=True)
        bpy.ops.pose.parent_selected_to_active()
        assert bones['Bone2.L'].use_connect is bones['Bone2.R'].use_connect is False, "Parenting op shouldn't connect bones."
        assert bones['Bone2.L'].parent == bones['Bone1.L'], "Parenting op failed."
        assert bones['Bone2.R'].parent == bones['Bone1.R'], "Parenting op didn't symmetrize."
        bpy.ops.pose.unparent_selected()
        if mode != 'EDIT':
            bpy.ops.pose.parent_active_to_all_selected()
            assert pbones['Bone1.L'].constraints[0].targets[0].subtarget == 'Bone2.L', "Parenting with Armature Constraint failed"
            pbones['Bone1.L'].constraints.remove(pbones['Bone1.L'].constraints[0])
        bpy.ops.pose.parent_and_connect()
        assert bones['Bone2.L'].use_connect is bones['Bone2.R'].use_connect is True, "Parent & connect op failed to connect"
        assert bones['Bone2.L'].parent == bones['Bone1.L'], "Parent & connect op failed to parent."
        assert bones['Bone2.R'].parent == bones['Bone1.R'], "Parent & connect op didn't symmetrize."


    for mode in ('POSE', 'EDIT', 'WEIGHT_PAINT'):
        bpy.ops.object.mode_set(mode='OBJECT')
        if mode == 'WEIGHT_PAINT':
            context.scene.objects['Cylinder'].select_set(True)
            context.view_layer.objects.active = context.scene.objects['Cylinder']

        bpy.ops.object.mode_set(mode=mode)
        run_bone_parent_ops(mode)

def select_bones(rig: Object, bone_names: list[str], select=True, *, expand=False, activate=True):
    for bone_name in bone_names:
        select_bone(rig, bone_name, select=select, expand=expand, activate=activate)

def select_bone(rig: Object, bone_name: str, select=True, *, expand=False, activate=True):
    if rig.mode == 'EDIT':
        select_ebone(rig.data.edit_bones[bone_name], select=select, expand=expand, activate=activate)
    else:
        select_pbone(rig.pose.bones[bone_name], select=select, expand=expand, activate=activate)

def select_pbone(pbone: PoseBone, select=True, *, expand=False, activate=True):
    rig: Object = pbone.id_data

    if not expand:
        for pb in pbone.id_data.pose.bones:
            pb.select = False

    if activate:
        rig.data.bones.active = rig.data.bones[pbone.name]
    pbone.select = select

def select_ebone(ebone: EditBone, select=True, *, expand=False, activate=True):
    if not expand:
        for eb in ebone.id_data.edit_bones:
            eb.select = eb.select_head = eb.select_tail = False

    ebone.select = ebone.select_head = ebone.select_tail = select
    for child_eb in ebone.children:
        if child_eb.use_connect:
            child_eb.select_head = select
    if ebone.parent:
        ebone.parent.select_tail = select
    if activate:
        ebone.id_data.edit_bones.active = ebone
