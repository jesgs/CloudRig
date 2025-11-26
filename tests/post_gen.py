import bpy
from bl_ext.cloudrig.CloudRig.utils import post_gen

rig = bpy.context.active_object
assert rig and rig.name == 'RIG-Simple'

post_gen.set_custom_property_value(rig, "Properties", "fk_hinge_left_bone1", 1.0)
assert rig.pose.bones["Properties"]["fk_hinge_left_bone1"] == 1.0

post_gen.set_custom_property_default(rig, "Properties", "fk_hinge_right_bone1", 0.5)
assert rig.pose.bones["Properties"]["fk_hinge_right_bone1"] == 0.5

post_gen.rename_bone(rig, "Properties", "Renamed Bone")
post_gen.rename_custom_property(rig, "Renamed Bone", "fk_hinge_right_bone1", "Renamed Property")
assert rig.pose.bones["Renamed Bone"]["Renamed Property"] == 0.5

post_gen.add_property_drivers(rig, bone_name="Renamed Bone", property_name='pose.bones["Renamed Bone"]["Renamed Property"]', data_path='["fk_hinge_left_bone1"]', driver_expressions="var")

post_gen.update_bone_collection(rig, 'ROOT-Bone1.L', 'FK Controls', 'add')
post_gen.update_bone_collection(rig, 'ROOT-Bone1.R', 'FK Secondary', 'remove')
post_gen.update_widget_properties(rig, 'FK-Bone1.L', wire_width=10)

post_gen.GLOBAL_clean_custom_properties()
post_gen.GLOBAL_rename_obdatas()
