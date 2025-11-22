import bpy

def test_metarig_cloud_human(context):
    generate_without_errors(context, 'META-Cloud_Human')

def test_metarig_sintel(context):
    generate_without_errors(context, 'META-Sintel')

def generate_without_errors(context, metarig_name: str):
    assert bpy.ops.object.cloudrig_metarig_add(metarig_name=metarig_name) == {'FINISHED'}
    context.active_object.cloudrig.generator.generate_test_action = True
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    assert len(context.active_object.cloudrig.generator.logs) == 0