
import bpy
import math
import os
import numpy as np

def print(data):
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type == 'CONSOLE':
                override = {'window': window, 'screen': screen, 'area': area}
                bpy.ops.console.scrollback_append(override, text=str(data), type="OUTPUT")       

def copy_anim_data(source_obj, target_obj):
    for bone in source_obj.pose.bones:
        ct = target_obj.constraints.new('COPY_TRANSFORMS')
        ct.influence = 1
        ct.name = bone.name
        ct.target = source_obj
        ct.subtarget = bone.name

    for i in range(0, 10):
        scene.frame_set(i)
        for bone in target_obj.pose.bones:
            source_bone = source_obj.pose.bones.get(bone.name)
            if source_bone is not None:
                bone.rotation_quaternion = source_bone.matrix_basis.to_quaternion()
                bone.keyframe_insert(data_path='rotation_quaternion')

# Clear existing mesh objects
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.object.select_by_type(type='MESH')
bpy.ops.object.delete()

# Set the file paths
fbx_path = "/home/sy/SkinMesh_Zero.fbx"
bvh_path = "/home/sy/repo/AMDM-public/output/base/amdm_style100_consist_new_rollout_0/out1.bvh"
output_path = "/home/sy/render/amdm_style100_consist_new_rollout_0/images/"
if not os.path.exists(output_path):
    os.makedirs(output_path)
# Import the FBX file
bpy.ops.import_scene.fbx(filepath=fbx_path)

bpy.ops.object.select_all(action='DESELECT')

# Replace 'object_name' with the name of the object you want to select
object_name = 'object_name'

# Check if the object exists and then select it
if object_name in bpy.data.objects:
    bpy.data.objects[object_name].select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects[object_name]
else:
    print(f"Object '{object_name}' not found.")

    
# Import the BVH file
bpy.ops.import_anim.bvh(filepath=bvh_path)

for obj in bpy.context.scene.objects:
    print(f"Object Name: {obj.name}, Type: {obj.type}, Location: {obj.location}")


# Assuming the armatures have the same structure
# Find the armatures
fbx_armature = None
bvh_armature = None
for obj in bpy.data.objects:
    if obj.type == 'ARMATURE':
        if fbx_armature is None:
            fbx_armature = obj
        else:
            bvh_armature = obj
            break

# Check if both armatures are found
if fbx_armature is not None and bvh_armature is not None:
    # Transfer animation data from BVH armature to FBX armature
    fbx_armature.animation_data_create()
    fbx_armature.animation_data.action = bvh_armature.animation_data.action

    # Optionally, delete the BVH armature as it's no longer needed
    bpy.data.objects.remove(bvh_armature)

# Set up rendering settings
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = output_path

# Set up camera and lighting (you may need to adjust this based on your scene)
bpy.ops.object.camera_add(location=(0, -5, 3), rotation=(1.0472, 0, 0))
bpy.ops.object.light_add(type='SUN', location=(5, -5, 5))
 
# Set up animation range
bpy.context.scene.frame_start = 0
frame_end =  bpy.context.object.animation_data.action.frame_range.y
if type(frame_end) is float:
    frame = int(frame_end)
bpy.context.scene.frame_end =frame_end

# Render animation
bpy.ops.render.render(animation=True)

# Save the rendered animation
bpy.ops.wm.save_as_mainfile(filepath=output_path + ".blend")

# Exit Blender
bpy.ops.wm.quit_blender()