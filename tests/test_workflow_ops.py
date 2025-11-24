import bpy

def test_symmetrize(context_sintel):
    metarig = context_sintel.active_object
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

def test_better_bone_extrude(context_sintel):
    metarig = context_sintel.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    my_bone = metarig.data.edit_bones['LipRing3.L']
    my_bone.select = my_bone.select_head = my_bone.parent.select_tail = True
    metarig.data.use_mirror_x = True
    bpy.ops.armature.better_bone_duplicate()
    new_bone = context_sintel.active_bone
    assert new_bone.name == 'LipRing6.L', f"Bone name didn't increment correctly: {new_bone.name}"
    assert 'LipRing6.R' in metarig.data.edit_bones, "Mirror bone name didn't increment correctly"
    bpy.ops.armature.select_all(action='DESELECT')
    metarig.data.edit_bones['LipRing6.L'].select_tail = True
    bpy.ops.armature.better_bone_extrude()
    new_bone = context_sintel.active_bone
    assert new_bone.name == 'LipRing7.L', f"Bone name didn't increment correctly: {new_bone.name}"