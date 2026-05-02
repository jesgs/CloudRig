import bpy


def test_generate_metarigs(context):
    from bl_ext.cloudrig.CloudRig import metarigs
    metarigs.delayed_refresh_metarig_list()
    for ui_name, metarig_name in metarigs.METARIG_NAMES:
        generate_metarig_without_errors(context, metarig_name)

def test_generate_samples(context):
    from bl_ext.cloudrig.CloudRig import metarigs
    metarigs.delayed_refresh_metarig_list()
    for ui_name, sample_name in metarigs.SAMPLE_NAMES:
        generate_sample_without_errors(context, sample_name)

def generate_sample_without_errors(context, sample_name: str):
    assert bpy.ops.object.cloudrig_sample_add(sample_name=sample_name) == {'FINISHED'}
    generate_without_errors(context, context.active_object)

def generate_metarig_without_errors(context, metarig_name: str):
    assert bpy.ops.object.cloudrig_metarig_add(metarig_name=metarig_name) == {'FINISHED'}
    generate_without_errors(context, context.active_object)

def generate_without_errors(context, metarig):
    bpy.ops.preferences.set_bone_color_presets(preset='LANARO')
    metarig = context.active_object
    metarig.cloudrig.generator.generate_test_action = True
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    logs = metarig.cloudrig.generator.logs
    assert len(logs) == 0, f"Metarig '{metarig.name}' has {len(logs)} generator warnings:\n\t" + "\n\t".join((log.description_short for log in logs))
