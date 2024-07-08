from fairmotion.data import bvh
import matplotlib.pyplot as plt
import numpy as np

#file = 'data/100STYLE/Aeroplane/Aeroplane_FW.bvh'
file = 'output/inpaint/amdm_style100_consist_new_rollout_4/out_angle_0_good_circle.bvh'
out_path = 'output/inpaint/amdm_style100_consist_new_rollout_4/out_angle_0_good_circle'
#file = 'output/path/amdm_style100_consist_new_rollout_4/out_angle_0_r.bvh'
#out_path = 'output/path/amdm_style100_consist_new_rollout_4/out_angle_0_traj_r'
#file = 'output/path/humor_style100/out_angle_0.bvh'
#out_path = 'output/path/humor_style100/out_angle_0_traj'
motion = bvh.load(file)
positions = motion.positions(local=False)  
orientations =  motion.rotations(local=False)  
heading = -np.arctan2(orientations[:,0,0,2], orientations[:, 0, 2, 2]) 
unit_dir = np.zeros((positions.shape[0],2))
unit_dir[:,0] = 1

sin = np.sin(heading) 
cos = np.cos(heading)
heading_rot = np.array([[cos,-sin],[sin,cos]])
heading_rot = heading_rot.transpose(2,0,1).transpose(0,2,1)
dxdy = np.matmul(heading_rot,unit_dir[...,None])
plt.plot(positions[:,0,0],positions[:,0,2])
np.save(out_path, positions[:,0,:])
for i in range(positions.shape[0]):
    #print(i,  dxdy[i,0,0], dxdy[i,1,0],positions[i,0,0], positions[i,0,1])
    plt.arrow(positions[i,0,0], positions[i,0,2], 10* dxdy[i,0,0],  10*dxdy[i,1,0],  head_width = 1, width = 0.2)
plt.savefig(out_path+'.png')