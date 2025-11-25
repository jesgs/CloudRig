import bpy

def test_generate_metarigs(context):
    from bl_ext.cloudrig.CloudRig import metarigs
    metarigs.delayed_refresh_metarig_list()
    for ui_name, metarig_name in metarigs.metarig_names:
        generate_metarig_without_errors(context, metarig_name)

def test_generate_samples(context):
    from bl_ext.cloudrig.CloudRig import metarigs
    metarigs.delayed_refresh_metarig_list()
    for ui_name, sample_name in metarigs.sample_names:
        generate_sample_without_errors(context, sample_name)

def generate_sample_without_errors(context, sample_name: str):
    assert bpy.ops.object.cloudrig_sample_add(sample_name=sample_name) == {'FINISHED'}
    context.active_object.cloudrig.generator.generate_test_action = True
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    num_logs = len(context.active_object.cloudrig.generator.logs)
    assert num_logs == 0, f"Sample '{sample_name}' has {len(num_logs)} generator warnings."

def generate_metarig_without_errors(context, metarig_name: str):
    assert bpy.ops.object.cloudrig_metarig_add(metarig_name=metarig_name) == {'FINISHED'}
    context.active_object.cloudrig.generator.generate_test_action = True
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    assert len(context.active_object.cloudrig.generator.logs) == 0
    