import bpy
import numpy as np
import math

fpath = "/home/sy/repo/AMDM-public/target/joystick/amdm_style100_consist_new_rollout_4/out_angle_0.npz"

cdict = np.load(fpath)
trans = cdict.f.trans 
trans_camera = cdict.f.trans_back
trans_left =  cdict.f.trans_left
trans_right =  cdict.f.trans_right
trans_front =  cdict.f.trans_front
angles = cdict.f.angles

vel = cdict.f.vel
jvel =  cdict.f.jvel
jang = cdict.f.jang

trans_camera[...,1] *= -1
trans[...,1] *= -1
trans_left[...,1] *= -1
trans_right[...,1] *= -1
trans_front[...,1] *= -1

# Ensure that there is a camera in the scene
if not bpy.context.scene.camera:
    bpy.ops.object.camera_add()
    
bpy.context.scene.camera = bpy.context.scene.objects["Camera"]
bpy.context.scene.camera.data.lens = 30 #23 3rd back

height_adj = 270 #160 3rd back
down_angle = -115 #-115

max_scale = 45
min_scale = 10
max_vel = 10
min_vel = 0

trans_camera[:,2] = height_adj

angles_camera = np.zeros((trans_camera.shape[0],3))
angles_camera[:,0] = math.radians(down_angle)
angles_camera[:,1] = np.pi

z_lookat_vec = (trans - trans_camera)[...,:2]
z_lookat_angle = np.pi - np.arctan2(z_lookat_vec[:,0],z_lookat_vec[:,1])
angles_camera[:,2] = z_lookat_angle

#cone_names = ["Cone","Cone.001","Cone.002"]
#cone_trans = [trans_front, trans_left, trans_right]
cone_names = ["Cone", "Cone.003"]
cone_trans = [trans_front, trans_front]

for i in range(trans_camera.shape[0]):
    
    for n,name in enumerate(cone_names):
        if jang is None or n<len(cone_names)-1:
            ang = angles[0,i]
            v = vel[0,i]
            h = 0
        else:
            ang = jang[0,i]
            v = jvel[0,i]
            h = 5
        cone_scale = min_scale + (max_scale - min_scale) * v/ max_vel
        bpy.data.objects[name].location = (cone_trans[n][i,0],cone_trans[n][i,1],h)
        bpy.data.objects[name].rotation_euler = (3.14/2, 0, ang)
        bpy.data.objects[name].scale = (21, 21, cone_scale)
        bpy.data.objects[name].keyframe_insert(data_path="location", frame=i)
        bpy.data.objects[name].keyframe_insert(data_path="rotation_euler", frame=i)
        bpy.data.objects[name].keyframe_insert(data_path="scale", frame=i)
    #bpy.data.objects["Cone.002"].location = (trans[i,0],trans[i,1],trans[i,2])
    #bpy.data.objects["Cone.002"].keyframe_insert(data_path="location", frame=i)
    #bpy.data.objects["Cone.003"].location = (trans_front[i,0],trans_front[i,1],trans_front[i,2])
    bpy.context.scene.camera.location = (trans_camera[i,0], trans_camera[i,1], trans_camera[i,2])
    bpy.context.scene.camera.rotation_euler = (angles_camera[i,0], angles_camera[i,1], angles_camera[i,2])  # Rotating the camera to face the front
    #bpy.context.scene.camera.rotation_euler[1] += math.radians(180)
    bpy.context.scene.camera.keyframe_insert(data_path="location", frame=i)
    bpy.context.scene.camera.keyframe_insert(data_path="rotation_euler", frame=i)
