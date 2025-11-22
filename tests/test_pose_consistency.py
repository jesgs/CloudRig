import bpy
from bpy.types import Object, PoseBone
from mathutils import Matrix
from hashlib import md5
from pathlib import Path

def test_pose_consistency(context):
    blend_path = Path(__file__).parent / Path("tests.blend")
    bpy.ops.wm.open_mainfile(filepath=blend_path.as_posix())
    metarigs_test(context)

#########################################

def pbone_to_hash(pbone: PoseBone) -> str:
	return md5("".join([str(e) for e in [
		pbone.matrix,
		pbone.bbone_scalein,
		pbone.bbone_scaleout,
		pbone.bbone_curveinx,
		pbone.bbone_curveinz,
		pbone.bbone_curveoutx,
		pbone.bbone_curveoutz,
		pbone.bbone_rollin,
		pbone.bbone_rollout,
		pbone.bbone_easein,
		pbone.bbone_easeout,
	]]).encode('utf-8')).hexdigest()

def is_pbone_visible(pbone: PoseBone) -> bool:
	is_any_collection_visible = any([coll.is_visible_effectively for coll in pbone.bone.collections])
	if not is_any_collection_visible:
		return False
	return not pbone.hide

def hash_pose(rig: Object, visible_only=True) -> list[list[[str, Matrix]]]:
	"""Crunch the pose of a rig into a hash for easy comparisons.
	We use list of list instead of list of tuples because it gets auto-converted
	to lists anyways when storing in a custom property, which we need to do."""
	if visible_only:
		pbones = [pb for pb in rig.pose.bones if is_pbone_visible(pb)]
	else:
		pbones = rig.pose.bones

	transforms = []
	for pb in sorted(pbones, key=lambda pb: pb.name):
		transforms.append([pb.name, pbone_to_hash(pb)])

	return transforms

def update_expected_hashes(context, metarig: Object, frame: int):
	"""This can be run manually in the .blend file if the rig results have changed on purpose."""
	context.scene.frame_current = frame
	metarig['expected_hashes'] = hash_pose(metarig.cloudrig.generator.target_rig)

def compare_hashes(context, metarig: Object, frame: int):
	context.scene.frame_current = frame
	hashes = hash_pose(metarig.cloudrig.generator.target_rig)
	return hashes == metarig['expected_hashes']

def regenerate_rig(context, rig: Object):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    rig.hide_set(False)
    context.view_layer.objects.active = rig
    bpy.ops.pose.cloudrig_generate()

def metarigs_test(context):
    for metarig_name, frame in (
        ('META-toon_chain_tests_1', 10),
        ('META-Cloud_Human', 20),
    ):
        metarig = bpy.data.objects[metarig_name]
        regenerate_rig(context, metarig)
        update_expected_hashes(context, metarig, frame)
        assert compare_hashes(context, metarig, frame), f"Metarig result has changed: {metarig.name}"
        print(f"{metarig.name} generated with expected transforms.")
