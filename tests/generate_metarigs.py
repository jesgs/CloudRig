import bpy

def generate_metarigs(context):
    generate_without_errors(context, 'META-Cloud_Human')
    generate_without_errors(context, 'META-Sintel')

def generate_without_errors(context, metarig_name: str):
    assert bpy.ops.object.cloudrig_metarig_add(metarig_name=metarig_name) == {'FINISHED'}
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    assert len(context.active_object.cloudrig.generator.logs) == 1