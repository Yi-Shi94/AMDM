import bpy
import glob

# Path to the BVH file
fbx_filepath = '/home/sy/Downloads/SkinMesh.fbx'
bvh_filepath = '/home/sy/repo/AMDM-public/output/out_bvh/*.bvh'
bvh_paths = glob.glob(bvh_filepath)

for path in bvh_paths:
    bpy.ops.import_anim.bvh(filepath=path)
    bpy.ops.import_scene.fbx(filepath=fbx_filepath)
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            if fbx_armature is None:
                fbx_armature = obj
            else:
                bvh_armature = obj
                break
