from fairmotion.data import bvh
import matplotlib.pyplot as plt
import numpy as np
import copy
def rad_to_matrix_2d(rad):
    cs = np.cos(rad)
    sn = np.sin(rad)
    out = np.array([[cs,-sn],[sn,cs]])
    if len(out.shape) == 2:
        return out
    out = np.transpose(out,(2,0,1))
    return out

#file = 'output/inpaint/amdm_style100_consist_new_rollout_4/out_angle_0.bvh'
#out_path = 'output/inpaint/amdm_style100_consist_new_rollout_4/out_angle_0_cam'

#bvh_file = 'output/base/amdm_style100_consist_new_rollout_4/stframe1700007/out_angle_2.bvh' #'data/100STYLE/Kick/Kick_FW.bvh'#
#out_path = 'output/base/amdm_style100_consist_new_rollout_4/stframe1700007/out_angle_2' #'data/100STYLE/Kick/Kick_FW_'#output/target/amdm_style100_consist_new_rollout_4/out_angle_0'
bvh_file = 'output/run/joystick/out0.bvh'
out_path = 'output/run/joystick/out0'
joystick_file = 'output/run/joystick/joystick.npy'

if joystick_file is not None:
    jf = np.load(joystick_file)
    jvel = jf[...,0]
    jang = jf[...,1]
else:
    jvel = None
    jang = None

manual_cam_height = 250
manual_cam_angle = -130

#offset_camera = np.array([0,-130])[..., None] # 3rd person from back
#angle_camera = 0
offset_camera = np.array([330,330])[..., None] #3rd person from front left
angle_camera = np.pi + np.arctan2(offset_camera[0],offset_camera[1])

offset_left = np.array([-40, 0])[...,None] #-180
offset_right = np.array([40, 0])[...,None] #-180
offset_front = np.array([0, 40])[...,None] #-180

motion = bvh.load(bvh_file)
positions = motion.positions(local=False)  
orientations =  motion.rotations(local=False)  

root_xyzs = np.zeros((positions.shape[0],3))
root_xyzs[...,:2] = positions[:,0,[0,2]]

root_dxdy = root_xyzs[1:,:2]-root_xyzs[:-1,:2]

heading = -np.arctan2(orientations[:,0,0,2], orientations[:, 0, 2, 2]) 
heading = heading % (2*np.pi)

cs = np.cos(heading)
heading_rot = rad_to_matrix_2d(heading)

root_dxdy_can = np.matmul(heading_rot.transpose(0,2,1)[1:],root_dxdy[...,None]).squeeze(-1)
vel = np.zeros((heading_rot.shape[0],2))#root_dxdy_can[...,[1]]

vel[:-1] = root_dxdy_can
vel[-1] = root_dxdy_can[-1]
vel = vel[None,...,0]
heading = heading[None, ...]

offset_camera = np.matmul(heading_rot,offset_camera).squeeze(-1)
offset_left = np.matmul(heading_rot, offset_left).squeeze(-1)
offset_right = np.matmul(heading_rot,offset_right).squeeze(-1)
offset_front = np.matmul(heading_rot,offset_front).squeeze(-1)

trans_back = copy.deepcopy(root_xyzs)
trans_front = copy.deepcopy(root_xyzs)
trans_left = copy.deepcopy(root_xyzs)
trans_right = copy.deepcopy(root_xyzs)

trans_back[...,:2] = trans_back[...,:2] + offset_camera
trans_back[...,2] = manual_cam_height

trans_front[...,:2] = trans_front[...,:2] + offset_front
trans_left[...,:2] = trans_left[...,:2] + offset_left
trans_right[...,:2] = trans_right[...,:2] + offset_right

#print(heading.shape, vel.shape, jvel.shape, jang.shape)
np.savez(out_path, trans=root_xyzs, trans_back=trans_back, trans_left=trans_left, trans_right=trans_right, trans_front=trans_front, angles=-heading, vel = vel, jvel = jvel, jang=jang)

