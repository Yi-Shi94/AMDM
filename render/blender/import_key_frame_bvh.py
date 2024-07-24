import bpy
import glob

import os.path as osp
import os
interval = 20
start_frame = 0
end_frame = 300
path = '/home/sy/repo/AMDM/output/base/amdm_lafan1_25s_eps/12300_500step_intro/1.bvh'
out_path = '/home/sy/repo/AMDM/output/base/amdm_lafan1_25s_eps/12300_500step_intro/1/'
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
            if count > end_frame:
                break
            if count < start_frame:
                continue
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
#fbx_filepath = glob.glob('/home/sy/SkinMesh_Zero.fbx')
bvh_filepaths = glob.glob(out_path +'/*.bvh')

for path in bvh_filepaths:
    bpy.ops.import_anim.bvh(filepath=path)
    #bpy.ops.import_scene.fbx(filepath=fbx_filepath[0])
