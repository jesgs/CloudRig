import bpy

def generate_metarigs():
    assert bpy.ops.object.cloudrig_metarig_add(metarig_name="META-Cloud_Human") == {'FINISHED'}
    assert bpy.ops.pose.cloudrig_generate() == {'FINISHED'}
    print("Metarig generated!")