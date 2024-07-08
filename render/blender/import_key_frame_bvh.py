import bpy
import glob

import os.path as osp
import os
interval = 10
start_frame = 56
end_frame = -1 
path = '/home/sy/repo/AMDM-public/output/inpaint/used_in_video_singe_inbet.bvh'
out_path = '/home/sy/repo/AMDM-public/output/inpaint/used_in_video_singe_inbet/'
os.makedirs(out_path,exist_ok=True)
bvh_f = open(path,'r')
lines = bvh_f.readlines()
pre = []
count = 0
num_frames = 0
frame_ratr = 0
pre_flag = True

for i, line in enumerate(lines):
    if line.strip() == 'MOTION':
        pre_flag = False
    elif line.strip().split()[0] == "Frames:":
        num_frames = int(line.strip().split()[-1])
    elif line.strip().split()[0] == "Frame":
        frame_ratr = float(line.strip().split()[-1])
    else:   
        if pre_flag:
            pre.append(line)
        else:
            if count % interval == 0:
                record_line = line
                out_name = osp.join(out_path,str(count)+'.bvh')
                with open(out_name, 'w') as f:
                    for pre_line in pre:
                        f.write(pre_line)
                    f.write('MOTION\n')
                    f.write('Frames: 1\n')
                    f.write('Frame Time: 1\n')
                    f.write(line)
            count += 1
bvh_f.close()

# Paths to the files
fbx_filepath = glob.glob('/home/sy/SkinMesh_Zero.fbx')
bvh_filepaths = glob.glob('/home/sy/repo/AMDM-public/output/inpaint/used_in_video_singe_inbet/*.bvh')

for path in bvh_filepaths:
    bpy.ops.import_anim.bvh(filepath=path)
    bpy.ops.import_scene.fbx(filepath=fbx_filepath[0])
