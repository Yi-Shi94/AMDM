
import os
import os.path as osp
import numpy as np
import copy

import dataset.util.geo as geo_util
import dataset.util.unit as unit_util
import dataset.util.plot as plot_util
from dataset.util.motion_struct import Skeleton, Joint, Motion
from scipy.spatial.transform import Rotation as R

def extract_sk_lengths(positions, linked_joints):
    #position: NxJx3
    #single frame rigid body restriction
    lengths = np.zeros((len(linked_joints),positions.shape[0]))
    for i,(st,ed) in enumerate(linked_joints):
        length =  np.linalg.norm(positions[:,st] - positions[:,ed], axis=-1)     
        lengths[i] = length
    return np.mean(lengths,axis=-1)

def get_parent_from_link(links):
    max_index = -1
    parents_dict = dict()
    parents = list()
    for pair in links:
        st, ed = pair
        if st>ed:
            st, ed = ed, st
        max_index = ed if ed>max_index else max_index
        parents_dict[ed] = st
    parents_dict[0] = -1
    for i in range(max_index+1):
        parents.append(parents_dict[i])
    return parents

def load_bvh_info(bvh_file_path):
    joint_name = []
    joint_parent = []
    joint_offset = []
    joint_rot_order = []
    joint_chn_num = []

    cnt = 0
    myStack = []
    root_joint_name = None
    frame_time = 0 
    
    with open(bvh_file_path, 'r') as file_obj:
        for line in file_obj:
            lineList = line.split()
            if (lineList[0] == "{"):
                myStack.append(cnt)
                cnt += 1

            if (lineList[0] == "}"):
                myStack.pop()

            if (lineList[0] == "OFFSET"):
                joint_offset.append([float(lineList[1]), float(lineList[2]), float(lineList[3])])

            if (lineList[0] == "JOINT"):
                joint_name.append(lineList[1])
                joint_parent.append(myStack[-1])
            
            elif (lineList[0] == "ROOT"):
                joint_name.append(lineList[1])
                joint_parent.append(-1)
                root_joint_name = lineList[1]

            elif (lineList[0] == "End"):
                joint_name.append(joint_name[-1] + '_end')
                joint_parent.append(myStack[-1])
                joint_rot_order.append(joint_rot_order[-1])

            elif (lineList[0] == "CHANNELS"):
                channel_num = lineList[1]
                joint_chn_num.append(int(channel_num))
                if joint_parent[-1] == -1:
                    rot_lst = lineList[5:]
                else:
                    rot_lst = lineList[2:]

                joint_rot_order.append(''.join([ob[0] for ob in rot_lst]))

            elif (lineList[0] == "Frame" and lineList[1] == "Time:"):
                frame_time = float(lineList[2])

    joint_offset = np.array(joint_offset).reshape(-1, 3)
    return joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time


def import_bvh(bvh_file, root_joint_name=None, end_eff=False):
    with open(bvh_file, "rb") as file:
        items = [w.decode() for line in file for w in line.strip().split()]
        n_items = len(items)

    cnt, depth = 0, 0
    joint_stack = [None, None]
    joint_list = []
    skeleton = Skeleton()

    # build skeleton
    while cnt < n_items and len(joint_stack) > 0:
        joint_cur = joint_stack[-1]
        item = items[cnt].lower()
        
        if item in ["root", "joint"]:
            name = items[cnt + 1]
            joint = Joint(name=name, idx=len(joint_list))
            
            if item == "joint":
                joint.add_parent(joint_cur)
            else:
                skeleton.set_root(joint)
            joint_stack.append(joint)
            joint_list.append(joint)
            cnt += 2

        elif item == "end" and items[cnt+1].lower() == 'site':
            name = 'end_eff_{}'.format(joint_cur._name)
            if end_eff:
                joint = Joint(name=name, idx=len(joint_list))
                joint_stack.append(joint)
                joint_list.append(joint)
                joint.add_parent(joint_cur)
            cnt += 2

        elif item == "offset":
            if (end_eff and name[:7] == 'end_eff') or name[:7] != 'end_eff': 
                x = float(items[cnt + 1])
                y = float(items[cnt + 2])
                z = float(items[cnt + 3])
                
                if joint_cur._parent_idx is not None:
                    coords = np.array([x,y,z])
                else:
                    coords = np.array([0,0,0])
                joint_cur.set_offset(coords)
            cnt += 4

        elif item == "channels":
            ndof = int(items[cnt + 1])
        
            axis_order = []
            assert ndof in [1, 2, 3, 6], "unsupported num of dof {} for joint {}".format(ndof, joint_cur._name)
            joint_cur.set_dof(ndof)

            for i in range(ndof):
                axis = items[cnt + 2 + i]
                if axis[1:] == 'position':
                    continue
                else:
                    axis_order.append(axis[0])

            joint_cur.set_rot_axis_order(''.join(axis_order))
            cnt += 2
            cnt += ndof

        elif item == "{":
            depth += 1
            cnt += 1

        elif item == "}":
            
            depth -= 1
            if not items[cnt-4].lower() == 'offset' and not end_eff and name[:7] == 'end_eff':
                joint_stack.pop()
            cnt += 1

            if depth == 0:
                break   

        elif item == "hierarchy":
            cnt += 1

        else:
            raise Exception("Unknown Token {}: {} {}".format(cnt, item, items[cnt-5:cnt+5]))

    skeleton.add_joints(joint_list)

    num_jnt = len(joint_list)
    motion = Motion(skeleton)

    # load motion info
    while cnt < n_items:
        item = items[cnt].lower()
        if item == 'motion':
            cnt += 1

        elif item == 'frames:':
            num_frames = int(items[cnt+1])
            cnt += 2

        elif item == 'frame' and items[cnt+1].lower() == 'time:':
            fps = int(1.0/float(items[cnt+2]))
            motion.set_fps(fps)
            cnt += 3
            break
    
    # load motion
    rotations = np.zeros((num_frames, num_jnt, 3, 3))
    root_trans = np.zeros((num_frames, 3))
    for idx_frame in range(num_frames):
        for idx_jnt in range(num_jnt):
            dof = joint_list[idx_jnt]._ndof
            rot_axis_order = joint_list[idx_jnt]._rot_axis_order
            vec = np.array([float(x) for x in items[cnt: cnt + dof]])
            if dof == 6:
                if joint_list[idx_jnt]._parent_idx is None:
                    root_trans[idx_frame] = vec[:3]
                    rotations[idx_frame, idx_jnt] = R.from_euler(rot_axis_order, vec[3:], degrees=True).as_matrix()               
                else:
                    if root_joint_name is not None and joint_list[idx_jnt]._name == root_joint_name:
                        root_trans[idx_frame] = vec[:3]
                    rotations[idx_frame, idx_jnt] = R.from_euler(rot_axis_order, vec[3:], degrees=True).as_matrix()
                cnt += dof

            elif 0 < dof <= 3:
                rotations[idx_frame, idx_jnt] = R.from_euler(rot_axis_order, vec[:dof], degrees=True).as_matrix() 
                cnt += dof

    motion.set_motion_frames(root_trans, rotations)
    return motion

def export_bvh(file_path, motion, offset_translate=None, offset_rotate=None):
    root_xyzs = motion._positions[:,0,:]
    joint_rotations = motion._rotations
    
    if offset_translate is not None:
        root_xyzs[:,0] += offset_translate[0]
        root_xyzs[:,2] += offset_translate[1]
    if offset_rotate is not None:
        #TODO
        pass
    
    joint_euler_order = 'ZYX'
    joint_eulers = geo_util.rotation_matrix_to_euler(joint_rotations, joint_euler_order) /np.pi*180

    joint_lst = motion._skeleton._joint_lst
    joint_names = [jnt._name for jnt in joint_lst]
    joint_parent = [jnt._parent_idx if jnt._parent_idx  is not None else -1 for jnt in joint_lst]
    joint_offset = motion._skeleton.get_joint_offset()
    target_fps = motion._fps
    output_as_bvh(file_path, root_xyzs, joint_eulers, joint_euler_order, joint_names, joint_parent, joint_offset, target_fps)


def output_as_bvh(file_path, root_xyz, joint_rot_eulers, joint_rot_order, joint_names, joint_parents, joint_offset, target_fps):
    child_lst = [[] for _ in joint_names]
    root_index = 0
    for i,i_p in enumerate(joint_parents):
        if i_p == -1:
            root_index = i
        else:
            child_lst[i_p].append(i)
    #print(child_lst)

    if isinstance(joint_rot_order, str):
        rot_order = [joint_rot_order for _ in range(len(joint_names))]
    elif isinstance(joint_rot_order, list) and len(joint_rot_order) == len(joint_names):
        rot_order = joint_rot_order
    else:
        raise NotImplementedError
    
    if osp.exists(file_path):
        os.remove(file_path)
    out_file = open(file_path,'w+')
    
    out_str = 'HIERARCHY\n'
    out_str+= 'ROOT {}\n'.format(joint_names[root_index])
    out_str+= '{\n'
    out_str+= ' OFFSET {:6f} {:6f} {:6f}\n'.format(joint_offset[root_index][0],joint_offset[root_index][2],joint_offset[root_index][1])
    out_str+= ' CHANNELS 6 Xposition Yposition Zposition {}rotation {}rotation {}rotation\n'.format(rot_order[root_index][0],rot_order[root_index][1],rot_order[root_index][2])
    
    out_file.write(out_str)
    
    def form_str(file, idx_joint, child_joints, depth):
        #print(child_joints,depth)
        if len(child_joints) == 0:
            end_eff_coord = [0,0,0]
            out_str = ' ' * depth + 'End Site\n'
            out_str += ' ' * depth + '{\n'
            out_str += ' ' * (depth+1) +'OFFSET {:6f} {:6f} {:6f}\n'.format(end_eff_coord[0], end_eff_coord[1], end_eff_coord[2])
            out_str += ' ' * depth + '}\n'
            file.write(out_str)
            return
        
        for i in range(len(child_joints)):
            idx_joint = child_joints[i]
            
            out_str = ' ' * depth + 'JOINT {}\n'.format(joint_names[idx_joint])
            out_str += ' ' * depth + '{\n'

            out_str+= ' ' * (depth +1) + "OFFSET {:6f} {:6f} {:6f}\n".format(joint_offset[idx_joint][0],joint_offset[idx_joint][1],joint_offset[idx_joint][2])
            out_str+= ' ' * (depth +1) + "CHANNELS 3 {}rotation {}rotation {}rotation\n".format(rot_order[idx_joint][0],rot_order[idx_joint][1],rot_order[idx_joint][2]) 
            file.write(out_str)
            form_str(file, idx_joint, child_lst[idx_joint], depth + 1)
            
            file.write(' ' * depth + '}\n')

    form_str(out_file, root_index, child_lst[root_index], 1)
    out_file.write('}\n')
    
    frames = joint_rot_eulers.shape[0]
    out_str = 'MOTION\n'
    out_str += 'Frames: {}\n'.format(frames)
    out_str += 'Frame Time: {:6f}\n'.format(1.0/target_fps)
    out_file.write(out_str)

    for i in range(frames):
        out_str = ''
        out_str += '{:6f} {:6f} {:6f}'.format(root_xyz[i][0],root_xyz[i][1],root_xyz[i][2])
        for r in joint_rot_eulers[i]:
            out_str += ' {:6f} {:6f} {:6f}'.format(r[0],r[1],r[2])
        out_str += '\n'
        out_file.write(out_str)
    out_file.close()



def read_bvh_loco(path, unit, target_fps, root_rot_offset=0, frame_start=None, frame_end=None):
    motion = import_bvh(path, end_eff=False)
    positions = motion._positions * unit_util.unit_conver_scale(unit) # (frames, joints, 3)
    rotations = motion._rotations #
    root_idx = motion._skeleton._root._idx
    
    if frame_start is not None and frame_end is not None:
        positions = positions[frame_start:frame_end]
        rotations = rotations[frame_start:frame_end]

    source_fps = motion._fps 
    if source_fps > target_fps:
        sample_ratio = int(source_fps/target_fps)
        positions = positions[::sample_ratio]
        rotations = rotations[::sample_ratio]
    
    nfrm, njoint, _ = positions.shape
    
    ori = copy.deepcopy(positions[0,root_idx])
    
    y_min = np.min(positions[0,:,1])
    ori[1] = y_min

    positions = positions - ori
    velocities_root = positions[1:,root_idx,:] - positions[:-1,root_idx,:]
    
    positions[:,:,0] -= positions[:,0,:1]
    positions[:,:,2] -= positions[:,0,2:]

    global_heading = -np.arctan2(rotations[:,root_idx,0,2], rotations[:, root_idx, 2,2]) 
    global_heading += root_rot_offset/180*np.pi

    global_heading_diff = global_heading[1:] - global_heading[:-1]
    
    global_heading_rot = np.array([geo_util.rot_yaw(x) for x in global_heading])
    #global_heading_rot_inv = global_heading_rot.transpose(0,2,1)

    positions_no_heading = np.matmul(np.repeat(global_heading_rot[:, None,:, :], njoint, axis=1), positions[...,None])
    
    velocities_no_heading = positions_no_heading[1:] - positions_no_heading[:-1] #np.matmul(np.repeat(global_heading_rot[:-1, None,:, :], njoint, axis=1), (positions[1:] - positions[:-1])[...,None])
    velocities_root_xy_no_heading = np.matmul(global_heading_rot[:-1], velocities_root[:, :, None]).squeeze()[...,[0,2]]
 
    rotations[:,0,...] = np.matmul(global_heading_rot, rotations[:,0,...]) 

    size_frame = 3+njoint*3+njoint*3+njoint*6
    final_x = np.zeros((nfrm, size_frame))

    final_x[1:,2] = global_heading_diff
    final_x[1:,:2] = velocities_root_xy_no_heading 
    final_x[:,3:3+3*njoint] = np.reshape(positions_no_heading, (nfrm,-1))
    final_x[1:,3+3*njoint:3+6*njoint] = np.reshape(velocities_no_heading, (nfrm-1,-1))
    final_x[:,3+6*njoint:3+12*njoint] = np.reshape(rotations[..., :, :2, :], (nfrm,-1))
    return final_x, motion


def read_bvh_hetero(path, unit, target_fps,  root_rot_offset=0, frame_start=None, frame_end=None):
    motion = import_bvh(path, end_eff=False)
    positions = motion._positions * unit_util.unit_conver_scale(unit) # (frames, joints, 3)
    rotations = motion._rotations #
    root_idx = motion._skeleton._root._idx
    
    if frame_start is not None and frame_end is not None:
        positions = positions[frame_start:frame_end]
        rotations = rotations[frame_start:frame_end]

    source_fps = motion._fps 
    if source_fps > target_fps:
        sample_ratio = int(source_fps/target_fps)
        positions = positions[::sample_ratio]
        rotations = rotations[::sample_ratio]
    
    nfrm, njoint, _ = positions.shape
    
    ori = copy.deepcopy(positions[0,root_idx])
    
    y_min = np.min(positions[0,:,1])
    ori[1] = y_min

    positions = positions - ori
    velocities_root = positions[1:,root_idx,:] - positions[:-1,root_idx,:]
    
    positions[:,:,0] -= positions[:,0,:1]
    positions[:,:,2] -= positions[:,0,2:]

    global_heading = - np.arctan2(rotations[:,root_idx,0,2], rotations[:, root_idx, 2,2]) 
    global_heading += root_rot_offset/180*np.pi
    global_heading_diff = global_heading[1:] - global_heading[:-1] #% (2*np.pi)
    global_heading_diff_rot = np.array([geo_util.rot_yaw(x) for x in global_heading_diff])
    global_heading_rot = np.array([geo_util.rot_yaw(x) for x in global_heading])
    #global_heading_rot_inv = global_heading_rot.transpose(0,2,1)

    positions_no_heading = np.matmul(np.repeat(global_heading_rot[:, None,:, :], njoint, axis=1), positions[...,None])
    
    velocities_no_heading = positions_no_heading[1:] - positions_no_heading[:-1] #np.matmul(np.repeat(global_heading_rot[:-1, None,:, :], njoint, axis=1), (positions[1:] - positions[:-1])[...,None])
    velocities_root_xy_no_heading = np.matmul(global_heading_rot[:-1], velocities_root[:, :, None]).squeeze()[...,[0,2]]
 
    rotations[:,0,...] = np.matmul(global_heading_rot, rotations[:,0,...]) 

    size_frame = 8+njoint*3+njoint*3+njoint*6
    final_x = np.zeros((nfrm, size_frame))

    final_x[1:,2:8] = geo_util.rotation_matrix_to_6d(global_heading_diff_rot)
    final_x[1:,:2] = velocities_root_xy_no_heading 
    final_x[:,8:8+3*njoint] = np.reshape(positions_no_heading, (nfrm,-1))
    final_x[1:,8+3*njoint:8+6*njoint] = np.reshape(velocities_no_heading, (nfrm-1,-1))
    final_x[:,8+6*njoint:8+12*njoint] = np.reshape(rotations[..., :, :2, :], (nfrm,-1))
    return final_x, motion

if __name__ == '__main__':
    pass
