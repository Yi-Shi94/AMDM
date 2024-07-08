import torch
import torch.nn.functional as F
import torch.optim as optim

import numpy as np
import math
import tqdm
import copy
import os
from scipy.spatial.transform import Rotation as R

from dataset import *

def get_link(parent):
    link_lst = []
    for idx, idx_par in enumerate(parent):
        if idx_par == -1:
            continue
        link_lst.append([idx,idx_par])
    return link_lst


def viz_diff(x, y, range_of_view):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    ax.set_xlim(-range_of_view, +range_of_view)
    ax.set_ylim(-range_of_view, +range_of_view)
    ax.set_zlim(0, 2*range_of_view)
    ax.scatter(x[:,0], x[:,1], x[:,2], c='b',alpha=1)
    ax.scatter(y[:,0], y[:,1], y[:,2], c='r',alpha=1)

    ax.set_xlabel('$X$')
    ax.set_ylabel('$Y$')
    ax.set_zlabel('$Z$')
    plt.show()


def ik(rot_last, jnt_cur, bvh_info, tol_change, max_iter, device = 'cuda:0'):
    #rot_last: 1xr
    #jnt_cur: (N-1)xjntx3
    #root_cur: (N-1)x3
    
    joint_name, joint_parent, joint_offset, joint_rot_order = bvh_info
    jnt_cur = torch.tensor(jnt_cur, requires_grad=False, device = device).float()
    joint_offset = torch.tensor(joint_offset, requires_grad=False, device =device).float()
    
    rot_last = torch.tensor(rot_last,device=device,requires_grad=False).float()
    drot = torch.zeros(rot_last.shape[-1], requires_grad=True, device= device)    
    optimizer = optim.LBFGS([drot], 
                    max_iter=max_iter, 
                    tolerance_change=tol_change,
                    line_search_fn="strong_wolfe")

    def f_loss(drot):
        motion_frame = torch.ones(3 + rot_last.shape[-1], device =device).float()
        motion_frame[:3] *= 0
        motion_frame[3:] *= rot_last+drot

        _, joint_positions,  _,   _ = fk_pt(joint_name, joint_parent, joint_offset, joint_rot_order, motion_frame)
        #viz_diff(jnt_cur.detach().cpu().numpy(), joint_positions.detach().cpu().numpy(), 100)
        loss = F.mse_loss(joint_positions,jnt_cur) 
        print(loss)
        return loss
    
    def closure():
        optimizer.zero_grad()
        objective = f_loss(drot)
        objective.backward()
        return objective

    optimizer.step(closure)
    rot_cur = rot_last + drot
    #viz_diff(jnt_cur.detach().cpu().numpy(), joint_positions.detach().cpu().numpy(), 100)
    return rot_cur.cpu().detach().numpy(), drot.cpu().detach().numpy()


def ik_progressive(rot_init, jnt_seq, bvh_info, tol_change, max_iter, device = 'cuda:0'):
    def rot(yaw):
        cs = np.cos(yaw)
        sn = np.sin(yaw)
        return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])
    '''
    joint_rot_order = bvh_info[-1]
    global_rot_euler = torch.tensor(rot_init[:3])
    global_mat = euler_to_matrix(joint_rot_order[0], global_rot_euler, degrees=True).numpy()
    yaw_rad = - np.arctan2(global_mat[0,2], global_mat[2,2])
    print(yaw_rad,'yaw')
    yaw_mat = rot(yaw_rad)

    global_mat_ = np.dot(global_mat,yaw_mat)
    rot_init[:3] = matrix_to_euler(global_mat_,joint_rot_order[0])
    '''
    rot_init[:3] = np.array([102.6,8.16,0.879])
    #print(jnt_seq.shape)
    rot_seq = np.zeros((jnt_seq.shape[0],rot_init.shape[-1]))
    rot_last = rot_init

    for i in tqdm.tqdm(range(jnt_seq.shape[0])):
        rot_cur, _ = ik(rot_last, jnt_seq[i], bvh_info, tol_change, max_iter, device)
        rot_last = copy.deepcopy(rot_cur)
        rot_seq[i] = rot_last
        #if i==0:
        #    print(rot_last[:3])
    return rot_seq


def euler_to_matrix(order, euler_angle, degrees):
    """
    input
        theta1, theta2, theta3 = rotation angles in rotation order (degrees)
        oreder = rotation order of x,y,z　e.g. XZY rotation -- 'xzy'
    output
        3x3 rotation matrix (numpy array)
    """
    device = euler_angle.device
    if degrees:
        euler_angle = euler_angle/180*math.pi
    #print(euler_angle.grad,'mat')
    
    matrix = torch.ones(3,3).to(device)
    c1 = torch.cos(euler_angle[0])
    s1 = torch.sin(euler_angle[0])
    c2 = torch.cos(euler_angle[1])
    s2 = torch.sin(euler_angle[1])
    c3 = torch.cos(euler_angle[2])
    s3 = torch.sin(euler_angle[2])
    
    if order=='XYZ':
        matrix=torch.tensor([[c2*c3, -c2*s3, s2],
                         [c1*s3+c3*s1*s2, c1*c3-s1*s2*s3, -c2*s1],
                         [s1*s3-c1*c3*s2, c3*s1+c1*s2*s3, c1*c2]])
    elif order=='XZY':
        matrix=torch.tensor([[c2*c3, -s2, c2*s3],
                         [s1*s3+c1*c3*s2, c1*c2, c1*s2*s3-c3*s1],
                         [c3*s1*s2-c1*s3, c2*s1, c1*c3+s1*s2*s3]])
    elif order=='YXZ':
        matrix=torch.tensor([[c1*c3+s1*s2*s3, c3*s1*s2-c1*s3, c2*s1],
                         [c2*s3, c2*c3, -s2],
                         [c1*s2*s3-c3*s1, c1*c3*s2+s1*s3, c1*c2]])
    elif order=='YZX':
        matrix=torch.tensor([[c1*c2, s1*s3-c1*c3*s2, c3*s1+c1*s2*s3],
                         [s2, c2*c3, -c2*s3],
                         [-c2*s1, c1*s3+c3*s1*s2, c1*c3-s1*s2*s3]])
    elif order=='ZYX':
        matrix[0,0] *= c1*c2
        matrix[0,1] *= c1*s2*s3-c3*s1
        matrix[0,2] *= s1*s3+c1*c3*s2

        matrix[1,0] *= c2*s1
        matrix[1,1] *= c1*c3+s1*s2*s3
        matrix[1,2] *= c3*s1*s2-c1*s3

        matrix[2,0] *= -s2
        matrix[2,1] *= c2*s3
        matrix[2,2] *= c2*c3

    elif order=='ZXY':
        matrix=torch.tensor([[c1*c3-s1*s2*s3, -c2*s1, c1*s3+c3*s1*s2],
                         [c3*s1+c1*s2*s3, c1*c2, s1*s3-c1*c3*s2],
                         [-c2*s3, s2, c2*c3]])
    return matrix


def _index_from_letter(letter: str) -> int:
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(
    axis: str, other_axis: str, data, horizontal: bool, tait_bryan: bool):
    """
    Extract the first or third Euler angle from the two members of
    the matrix which are positive constant times its sine and cosine.

    Args:
        axis: Axis label "X" or "Y or "Z" for the angle we are finding.
        other_axis: Axis label "X" or "Y or "Z" for the middle axis in the
            convention.
        data: Rotation matrices as tensor of shape (..., 3, 3).
        horizontal: Whether we are looking for the angle for the third axis,
            which means the relevant entries are in the same row of the
            rotation matrix. If not, they are in the same column.
        tait_bryan: Whether the first and third axes in the convention differ.

    Returns:
        Euler Angles in radians for each matrix in data as a tensor
        of shape (...).
    """

    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[..., i1], data[..., i2])
    if tait_bryan:
        return np.arctan2(-data[..., i2], data[..., i1])
    return np.arctan2(data[..., i2], -data[..., i1])


def matrix_to_euler(matrix, order):
    """
    Convert rotations given as rotation matrices to Euler angles in radians.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).
        order: Convention string of three uppercase letters.

    Returns:
        Euler angles in radians as tensor of shape (..., 3).
    """
    if len(order) != 3:
        raise ValueError("order must have 3 letters.")
    
    if order[1] in (order[0], order[2]):
        raise ValueError(f"Invalid order {order}.")
    
    for letter in order:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    
    if matrix.shape[-1] != 3 or matrix.shape[-2] != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    
    i0 = _index_from_letter(order[0])
    i2 = _index_from_letter(order[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = np.arcsin(
            matrix[..., i0, i2] * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = np.arccos(matrix[..., i0, i0])
    
    central_angle = central_angle[...,None]
    o = (
        _angle_from_tan(
            order[0], order[1], matrix[..., i2], False, tait_bryan
        )[...,None],
        central_angle,
        _angle_from_tan(
            order[2], order[1], matrix[..., i0, :], True, tait_bryan
        )[...,None],
    )
    return np.concatenate(o, -1)


def fk_pt(joint_name, joint_parent, joint_offset, joint_rot_order,  motion_data_cur_frame, device='cuda:0'):

    """
        joint_positions: np.ndarray，形状为(M, 3)的numpy数组，包含着所有关节的全局位置
        joint_orientations: np.ndarray，形状为(M, 4)的numpy数组，包含着所有关节的全局旋转(四元数)
    Tips:
        1. joint_orientations的四元数顺序为(x, y, z, w)
        2. from_euler时注意使用大写的XYZ
    """
    
    channals_num = (len(motion_data_cur_frame) -3) // 3
    root_position = motion_data_cur_frame[:3]
    rotations = torch.zeros((channals_num, 3)).to(device).float()
    joint_rotations = torch.zeros((channals_num, 3, 3)).to(device).float()
    #print(len(joint_rot_order), motion_data_cur_frame.shape[0], channals_num)
    for i in range(channals_num):
        rot_order = joint_rot_order[i]
        rotations[i] = motion_data_cur_frame[3+3*i: 6+3*i]
        joint_rotations[i] = euler_to_matrix(rot_order, rotations[i,:3], degrees=True)#.as_matrix()
    
    cnt = 0
    num_jnt = len(joint_name)
    joint_positions = torch.zeros((num_jnt, 3)).to(device).float()
    joint_orientations = torch.zeros((num_jnt, 3, 3)).to(device).float()
    joint_offset = joint_offset.float()
    
    for i in range(num_jnt):
        rot_order = joint_rot_order[i]
        if joint_parent[i] == -1: #root
            joint_positions[i] = root_position
            joint_orientations[i] = euler_to_matrix(rot_order, rotations[cnt,:3], degrees=True)#.as_matrix()
            #joint_orientations[i] = np.matmul(offset_mat,cur_joint_orientations)
        else:
            if "_end" not in joint_name[i]:     # 末端没有CHANNELS
                cnt += 1
            r = euler_to_matrix(rot_order, rotations[cnt,:3], degrees=True)
            joint_orientations[i] = torch.matmul(joint_orientations[joint_parent[i]].clone(), r)
            joint_positions[i] = joint_positions[joint_parent[i]] + torch.matmul(joint_orientations[joint_parent[i]].clone(),joint_offset[i])
    return  root_position, joint_positions, joint_orientations, joint_rotations


def fk(joint_name, joint_parent, joint_offset, joint_rot_order,  motion_data_cur_frame, offset_mat=np.eye(3)):
    """
        joint_positions: np.ndarray，形状为(M, 3)的numpy数组，包含着所有关节的全局位置
        joint_orientations: np.ndarray，形状为(M, 4)的numpy数组，包含着所有关节的全局旋转(四元数)
    Tips:
        1. joint_orientations的四元数顺序为(x, y, z, w)
        2. from_euler时注意使用大写的XYZ
    """
    
    channals_num = (len(motion_data_cur_frame) -3) // 3
    root_position = motion_data_cur_frame[:3]
    rotations = np.zeros((channals_num, 3), dtype=np.float64)
    joint_rotations = np.zeros((channals_num, 3, 3), dtype=np.float64)
    
    for i in range(channals_num):
        rot_order = joint_rot_order[i]
        rotations[i] = motion_data_cur_frame[3+3*i: 6+3*i]
        mat =  R.from_euler(rot_order, [rotations[i][0], rotations[i][1], rotations[i][2]], degrees=True).as_matrix()
        joint_rotations[i] = mat
    
    cnt = 0
    num_jnt = len(joint_name)
    joint_positions = np.zeros((num_jnt, 3), dtype=np.float64)
    joint_orientations = np.zeros((num_jnt, 3, 3), dtype=np.float64)
    
    for i in range(num_jnt):
        
        rot_order = joint_rot_order[i]
        if joint_parent[i] == -1: #root
            joint_positions[i] = root_position
            cur_joint_orientations = R.from_euler(rot_order, [rotations[cnt][0], rotations[cnt][1], rotations[cnt][2]], degrees=True).as_matrix()
            joint_orientations[i] = np.matmul(offset_mat,cur_joint_orientations)

        else:
            if "_end" not in joint_name[i]:     # 末端没有CHANNELS
                cnt += 1
            r = R.from_euler(rot_order, [rotations[cnt][0], rotations[cnt][1], rotations[cnt][2]], degrees=True)
            joint_orientations[i] = (R.from_matrix(joint_orientations[joint_parent[i]]) * r).as_matrix()
            joint_positions[i] = joint_positions[joint_parent[i]] + R.from_matrix(joint_orientations[joint_parent[i]]).apply(joint_offset[i])
    return  root_position, joint_positions, joint_orientations, joint_rotations


def load_motion_data(bvh_file_path, num_frames=-1):
    """part2 辅助函数，读取bvh文件"""
    with open(bvh_file_path, 'r') as f:
        lines = f.readlines()
        for i in range(len(lines)):
            if lines[i].startswith('Frame Time'):
                break

        motion_data = []
        frame_idx = 0
        for line in lines[i+1:]:
            data = [float(x) for x in line.split()]
            
            if len(data) == 0:
                break

            if num_frames!=-1 and frame_idx> num_frames:
                break
            
            frame_idx += 1

            motion_data.append(np.array(data).reshape(1,-1))
        motion_data = np.concatenate(motion_data, axis=0)
    return motion_data

transfer_map = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 
                6: 5, 7: 6, 8: 7, 9: 8, 10: 8, 
                11: 9, 12: 10, 13: 11, 14: 12, 15: 13, 
                16: 13, 17: 14, 18: 15, 19: 16, 20: 17, 
                21: 17, 22: 18, 23: 19, 24: 20, 25: 21, 26: 21}
rev_transfer_map = {}


for k,v in transfer_map.items():
    v = transfer_map[k]
    if v not in rev_transfer_map:
        rev_transfer_map[v] = k

def retarget_pose(anchor_orientation, poses, joint_parent, joint_rot_order):
    #channel_num = poses.shape[-1] // 3 -1  #njnt+1
    new_poses = np.zeros_like(poses)
    new_poses[:,:3] = poses[:,:3]
    num_seq = poses.shape[0]

    # Stationary: Q _ L pose-> T pose 
    Q_l2t_lst = anchor_orientation 
    Q_l2t_inv_lst = np.zeros((len(joint_parent),3,3))
    for j in range(len(joint_parent)):
        Q_l2t_inv_lst[j] = anchor_orientation[j].transpose(1,0)
    
    # For every frame:
    for n in range(num_seq):
        # For every joint:
        i_chn = -1.5
        for j in range(len(joint_parent)):
            if transfer_map[j] == i_chn:
                continue
            i_chn = transfer_map[j]
            eur_l = poses[n,(3+i_chn*3):(3+(i_chn+1)*3)]
            #if j == 6:
            #    from IPython import embed; embed()
            R_cur_l = R.from_euler(joint_rot_order[0], [eur_l[0], eur_l[1], eur_l[2]], degrees=True).as_matrix()
            Q_cur_l2t_inv = Q_l2t_inv_lst[j]

            if joint_parent[j] == -1:
                R_cur_t = np.dot(R_cur_l, Q_cur_l2t_inv)

            else:    
                Q_par_l2t = Q_l2t_lst[joint_parent[j]]
                R_cur_t = np.dot(np.dot(Q_par_l2t, R_cur_l), Q_cur_l2t_inv)
                
            new_euler = R.from_matrix(R_cur_t).as_euler(joint_rot_order[0], degrees=True)        
            new_poses[n,(3+i_chn*3):(3+(i_chn+1)*3)] = new_euler
    return new_poses

    
def reform_norm_skel(anchor_pose, old_offset, joint_name, joint_parent, joint_rot_order):
    #print(anchor_pose.shape)
    _, joint_positions, joint_orientations, joint_rotations = \
            fk(joint_name, joint_parent, old_offset, joint_rot_order, anchor_pose)
    
    new_offset = np.zeros_like(old_offset)
    for i in range(len(joint_name)):
        if joint_parent[i] == -1:
            offset = old_offset[i]
            continue
        parent_idx = joint_parent[i]
        offset = joint_positions[i] - joint_positions[parent_idx]
        new_offset[i] = offset

    root_idx = joint_parent.index(-1)
    new_offset[root_idx,1] = joint_positions[root_idx,1]
    
    return new_offset, joint_orientations


def load_joint_info(bvh_file_path):
    """请填写以下内容
    输入： bvh 文件路径
    输出:
        joint_name: List[str]，字符串列表，包含着所有关节的名字
        joint_parent: List[int]，整数列表，包含着所有关节的父关节的索引,根节点的父关节索引为-1
        joint_offset: np.ndarray，形状为(M, 3)的numpy数组，包含着所有关节的偏移量

    Tips:
        joint_name顺序应该和bvh一致
    """
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
                #joint_name.append(joint_name[-1] + '_end')
                #joint_parent.append(myStack[-1])
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
    joint_offset[joint_name.index(root_joint_name)] *= 0
    return joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time

def output_bvh_from_bvh(out_bvh_path, ori_bvh_path, motion, joint_name, offset):
    print('outputing data:')
    frm = len(motion)    
    bone_info_endl = -1
    ori_kept_line = []
    
    #_, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time = load_joint_info(ori_bvh_path)
    #joint_offset = reform_norm_skel(motion[0], joint_offset, joint_parent, joint_rot_order)
    #motion = reform_norm_pose(motion[0], motion)
    with open(ori_bvh_path, 'r') as file_obj:
        cur_jnt_name = None
        num_tab = 0
        for i, line in enumerate(file_obj):
            
            lineList = line.strip().split()

            if lineList[0] == 'Frame' and lineList[1] == 'Time:':
                ori_kept_line.append(line)
                bone_info_endl = i
                print(i, lineList, 'ended')
                break
            
            elif lineList[0] == 'Frames:':
                ori_kept_line.append('Frames: {}\n'.format(frm))

            elif lineList[0] == '{':
                ori_kept_line.append('\t'*num_tab+'{\n')
                num_tab += 1

            elif lineList[0] == '}':
                num_tab -= 1
                ori_kept_line.append('\t'*num_tab+'}\n')

            elif lineList[0] in ['ROOT','JOINT']:
                cur_jnt_name = lineList[1]
                ori_kept_line.append(line)

            elif (len(lineList)>1 and lineList[0]== 'End' and lineList[1]== 'Site'):
                cur_jnt_name = cur_jnt_name + '_end'
                ori_kept_line.append(line)


            elif lineList[0] == 'OFFSET':
                if offset is None:
                    ori_kept_line.append(line)
                    continue

                cur_offset = offset[joint_name.index(cur_jnt_name)]
                ori_kept_line.append('\t'*num_tab+'OFFSET {:.6f} {:.6f} {:.6f}\n'.format(cur_offset[0],cur_offset[1],cur_offset[2]))

            elif lineList[0] == 'MOTION':
                bone_info_endl = i
                ori_kept_line.append(line)

            else:
                ori_kept_line.append(line)

    with open(out_bvh_path, 'w') as file_obj:
        for line in ori_kept_line:
            file_obj.write(line)

        for i, rot_vec in enumerate(motion):
            rot_str = ' '.join([str('{:.6f}'.format(x)) for x in list(rot_vec)])+'\n'
            file_obj.write(rot_str)
    return

def dxdydth_to_traj(dxdydr, scale=1):
    def rot(yaw):
        cs = np.cos(yaw)
        sn = np.sin(yaw)
        return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])
    
    dxdy = dxdydr[:,:2]
    dr = dxdydr[:,2] 
    
    dpm = np.array([[0.0,0.0,0.0]])
    dpm_lst = np.zeros((dxdy.shape[0],3))
    yaws = np.cumsum(dr)
    yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)
    rots = np.zeros((dxdy.shape[0],3,3))

    for i in range(1, dxdy.shape[0]):
        rot_yaw = rot(yaws[i])
        rots[i] = rot_yaw
        cur_pos = np.zeros((1,3))
        cur_pos[0,0] = dxdy[i,0]
        cur_pos[0,2] = dxdy[i,1]
        dpm += np.dot(cur_pos,rot_yaw)
        dpm_lst[i,:] = copy.deepcopy(dpm)

    return dpm_lst, rots

def ik_x_to_outmot(x, jnt_num, bvh_ori_file, bvh_out_file, st_idx=None, st_frame=None, ik=True, x_flip=False, max_iter=500, tol_change=1e-9, smooth_level=3):
    def transfer(new_jnt_num, old_jnt, transfer_map):
        
        N = old_jnt.shape[0]
        new_jnt = np.zeros((N, new_jnt_num, 3))
        for i in range(new_jnt_num):
            new_jnt[:,i] = old_jnt[:,transfer_map[i]]
        return new_jnt
    
    joint_name, joint_parent, joint_offset, joint_rot_order, _ , _ = load_joint_info(bvh_ori_file)
    links = get_link(joint_parent)

    bvh_info = [joint_name, joint_parent, joint_offset, joint_rot_order]
    dxdydth = x[:,:3]
    joint_pos = x[:,3:3+jnt_num*3]
    
    trajs_3d, rots = dxdydth_to_traj(dxdydth)

    assert st_idx is not None or st_frame is not None
    if st_frame is None:
        rot_init = load_motion_data(bvh_ori_file)[st_idx,3:]
    else:
        rot_init = st_frame[3:]
        #print(joint_pos.shape)

    joint_pos = joint_pos.reshape(-1, jnt_num, 3)
    #vis_sk_s(joint_pos, skel_dict['LAFAN1']['links'],save_path=bvh_out_file+'/inf')
    '''
    dir_names = [['LeftUpLeg','RightUpLeg'],
                    ['LeftLeg','RightLeg'],
                    ['LeftFoot','RightFoot'],
                    ['LeftToe','RightToe'],
                    ['LeftToe_end','RightToe_end'],
                    ['LeftShoulder','RightShoulder'],
                    ['LeftArm','RightArm'],
                    ['LeftForeArm','RightForeArm'],
                    ['LeftHand','RightHand'],
                    ['LeftHand_end','RightHand_end']]

    for pair in dir_names:
        idxa = joint_name.index(pair[0])
        idxb = joint_name.index(pair[1])

        mid = new_joint_pos[:,idxb]
        new_joint_pos[:,idxb]  = new_joint_pos[:,idxa]
        new_joint_pos[:,idxa] = mid
            '''
    heights = joint_pos[:,0,1] * 30.48

    print('rot',rots.shape)
    print('jt',joint_pos.shape)

    for i in range(rots.shape[0]):
        joint_pos[i] = np.dot(joint_pos[i], rots[i])

    joint_pos *= 30.48
    trajs_3d *= 30.48

    if x_flip:
        joint_pos[:,:,0] = -joint_pos[:,:,0]
        trajs_3d[:,0] = -trajs_3d[:,0]
    joint_pos = joint_pos + trajs_3d[:,None,...]
    joint_pos[:,:,1] -= np.min(joint_pos[:1,:,1])
    joint_pos -= joint_pos[:1,:1,:]
    
    #vis_multiple(joint_pos, LEFAN1_links, 20)
    #vis_sk_s(joint_pos, LEFAN1_links,save_path=bvh_out_file+'/inf')
    joint_pos_ = joint_pos - joint_pos[:,:1,:] 

    transfer_map = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 8, 11: 9, 12: 10, 13: 11, 14: 12, 15: 13, 16: 13, 17: 14, 18: 15, 19: 16, 20: 17, 21: 17, 22: 18, 23: 19, 24: 20, 25: 21, 26: 21}
    rev_transfer_map = {}
    for k in transfer_map:
        v = transfer_map[k]
        rev_transfer_map[v] = k
    
    #_, joint_positions,  _,   _ = fk_pt(joint_name, joint_parent, joint_offset, joint_rot_order, motion_frame)
    #joint_positions = joint_positions.cpu().detach().numpy()
    #joint_positions -= joint_positions[0]
    #motion_frame = torch.from_numpy(load_motion_data(bvh_ori_file)[st_idx]).float().cuda()
    #  
    new_joint_pos = transfer(27, joint_pos_, transfer_map)
    #print(len(joint_name), joint_pos_.shape, new_joint_pos.shape)

    out_motion = np.zeros((x.shape[0]-1, rot_init.shape[-1]+3))
    out_motion_  = ik_progressive(rot_init, new_joint_pos[1:], bvh_info, max_iter=max_iter, tol_change=tol_change)

    out_motion[:,:3] = trajs_3d[1:,:]
    out_motion[:,3:] = out_motion_
    out_motion[:,1] = heights[1:]

    joint_offset = torch.from_numpy(joint_offset).float()
    ik_output = []

    for  i in range(1, out_motion.shape[0]):
        out_mot = torch.from_numpy(out_motion[i]).float()
        _, ik_points,  _,   _ = fk_pt(joint_name, joint_parent, joint_offset, joint_rot_order, out_mot, device='cpu')
        ik_output.append(ik_points.numpy())
        #inf_joints = joint_pos[i] + trajs_3d[i]
        #viz_diff(ik_points, inf_joints, range_of_view=100)
    
    ik_output = np.array(ik_output)
    ik_output = transfer(22, ik_output, rev_transfer_map)
    #vis_sk_s(ik_output, LEFAN1_links,save_path=bvh_out_file+'/fked')
    #print(ik_output.shape)
    #num_frame= ik_output.shape[0]
    
    #ik_output = moving_average(ik_output.reshape(ik_output.shape[0],-1), window_size=smooth_level).reshape(num_frame,-1,3)
    output_bvh_from_bvh(bvh_out_file, bvh_ori_file, out_motion, joint_name, joint_offset)


def vis_multiple(ax, xs, tr, links, c, skip=150):
    
    #fig = plt.figure()
    #ax = fig.add_subplot(111, projection='3d')

    acum_dist_thres = np.linalg.norm(tr[0]-tr[1]) * 30
    
    cur_acum_dist = 0.0
    last_idx = 0
    #print(xs.shape, tr.shape)
    xs = xs.reshape((xs.shape[0], -1, 3))
    for i in range(1,xs.shape[0]):
        cur_acum_dist += np.linalg.norm(tr[i]-tr[i-1])
        ax.plot([tr[i,0],tr[i-1,0]],[tr[i,1],tr[i-1,1]],[0,0],color=c)
        if cur_acum_dist >= acum_dist_thres:
        #ax.scatter(xs[i,:,0],  xs[i, :, 1], xs[i, :, 2])
            pass
            #tr_last = tr[last_idx]
            #ax.plot([tr_last[0],tr[i,0]],[tr_last[1],tr[i,1]],[0,0],color=c)

            #for st,ed in links:
            #   pt_st = xs[i,st]
            #    pt_ed = xs[i,ed]
            #    ax.plot([pt_st[0],pt_ed[0]],[pt_st[2],pt_ed[2]],[pt_st[1],pt_ed[1]],color=c)
            #    last_idx = i
            #    cur_acum_dist = 0.0


def vis_multiple_(ax, xs, links, c, skip=150):
    
    #fig = plt.figure()
    #ax = fig.add_subplot(111, projection='3d')
    tr = xs[:,0,[0,2]]
    h = xs[:,0,1]
    acum_dist_thres = np.linalg.norm(tr[0]-tr[1]) * 10
    
    cur_acum_dist = 0.0
    #print(xs.shape, tr.shape)
    xs = xs.reshape((xs.shape[0], -1, 3))
    ax.scatter(tr[0,0],tr[0,1],[0,0],color='g')

    for i in range(1,xs.shape[0]):
        cur_acum_dist += np.linalg.norm(tr[i]-tr[i-1])
        ax.plot([tr[i,0],tr[i-1,0]],[tr[i,1],tr[i-1,1]],[h[i],h[i-1]],color=c)
        if cur_acum_dist >= acum_dist_thres:
            #for st,ed in links:
            #    pt_st = xs[i,st]
            #    pt_ed = xs[i,ed]
            #    ax.plot([pt_st[0],pt_ed[0]],[pt_st[2],pt_ed[2]],[pt_st[1],pt_ed[1]],color=c)
            #    last_idx = i
            cur_acum_dist = 0.0

    ax.scatter(tr[-1,0],tr[-1,1],0,color='b')


    #ax.set_xlabel('$X$')
    #ax.set_ylabel('$Y$')
    #ax.set_zlabel('$Z$')
    #ax.axis('off')
    #plt.show()

def vis_traj(tr):
    fig = plt.figure()
    x = tr[:,0]
    y = tr[:,2]
    plt.plot(x,y)
    plt.show()
    #plt.close()


def viz_diff(x, y, range_of_view):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    ax.set_xlim(-range_of_view, +range_of_view)
    ax.set_ylim(-range_of_view, +range_of_view)
    ax.set_zlim(0, 2*range_of_view)
    ax.scatter(x[:,0], x[:,1], x[:,2], c='b',alpha=1)
    ax.scatter(y[:,0], y[:,1], y[:,2], c='r',alpha=1)

    ax.set_xlabel('$X$')
    ax.set_ylabel('$Y$')
    ax.set_zlabel('$Z$')
    plt.show()


def vis_sk_s(x, links, view_range=10, show_ani=True, save_path=None):
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import axes3d, Axes3D

    def rot(yaw):
        cs = np.cos(yaw)
        sn = np.sin(yaw)
        return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])
    
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    if isinstance(x, torch.Tensor):
        x = x.cpu().detach().numpy()
    
    if x.shape[-1] <= 267 and x.shape[-1]>=69:
        dxdy = x[...,:2] 
        dr = x[...,2]
        x = np.reshape(x[...,3:69],(-1,22,3))
        
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)

        for i in range(1,x.shape[0]):
           
           cur_pos = np.zeros((1,3))
           cur_pos[0,0] = dxdy[i,0]
           cur_pos[0,2] = dxdy[i,1]
           dpm += np.dot(cur_pos,rot(yaws[i]))
           dpm_lst[i,:] = copy.deepcopy(dpm)
           x[i,:,:] = np.dot(x[i,:,:],rot(yaws[i])) + copy.deepcopy(dpm)

    elif x.shape[-1] == 66:
        x = np.reshape(x,(-1,22,3))

    if x.shape[0] == 1:
        x = x[0]
    elif show_ani:
        import matplotlib.animation as animation
    
    if len(x.shape)==2:    
        ax.scatter(x[:,0],  x[:, 2], x[:, 1])

        for st,ed in links:
            pt_st = x[st]
            ed_st = x[ed]
            ax.plot([pt_st[0],ed_st[0]],[pt_st[2],ed_st[2]],[pt_st[1],ed_st[1]],color='r')

        ax.set_xlim(-10, 10)
        ax.set_ylim(-0, 20)
        ax.set_zlim(-10, 10)
        
    elif len(x.shape)==3:
        if not show_ani:
            stop_idx = x.shape[0]
            for i in range(0,stop_idx,5):
                ax.scatter(x[i,:,0],  x[i, :, 2], x[i, :, 1])

                for st,ed in links:
                    pt_st = x[i,st]
                    pt_ed = x[i,ed]
                    ax.plot([pt_st[0],pt_ed[0]],[pt_st[1],pt_ed[1]],[pt_st[2],pt_ed[2]],color='r')

            ax.set_xlim(-10, 10)
            ax.set_ylim(-0, 20)
            ax.set_zlim(-10, 10)

            ax.set_xlabel('$X$')
            ax.set_ylabel('$Y$')
            ax.set_zlabel('$Z$')
        else:
             
            link_data = np.zeros((len(links),x.shape[0]-1,3,2))
            xini = x[0]
            
            link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,2],xini[ed,2]],[xini[st,1],xini[ed,1]],color='r')[0]
                            for st,ed in links]

            ax.set_xlabel('$X$')
            ax.set_ylabel('$Y$')
            ax.set_zlabel('$Z$')
            
            for i in range(1,x.shape[0]):
                
                for j,(st,ed) in enumerate(links):
                    pt_st = x[i-1,st] #- y_rebase
                    pt_ed = x[i-1,ed] #- y_rebase
                    link_data[j,i-1,:,0] = pt_st
                    link_data[j,i-1,:,1] = pt_ed
                    
            def update_links(num, data_lst, obj_lst):
                #print(data_lst.shape)
                
                cur_data_lst = data_lst[:,num,:,:] 
                cur_root = cur_data_lst[4,:,0]
                root_x = cur_root[0]
                root_z = cur_root[2]
                
                for obj, data in zip(obj_lst, cur_data_lst):
                    obj.set_data(data[[0,2],:])
                    obj.set_3d_properties(data[1,:])
                    
                    ax.set_xlim(root_x-5, root_x+5)
                    ax.set_zlim(0, 10)
                    ax.set_ylim(root_z-5, root_z+5)
            #print(x.shape)
            line_ani = animation.FuncAnimation(fig, update_links, x.shape[0]-1, fargs=(link_data, link_obj),
                                   interval=50, blit=False)
            if save_path is not None:
                writergif = animation.PillowWriter(fps=30) 
                line_ani.save(save_path+'.gif', writer=writergif)

    if save_path is None:
        plt.show()
    plt.close()




def output_offline(st_idx = 1300, num_trial=5, num_steps=300, optimize=True):
    from train_diffusion import infer
    
    device = 'cuda:0'
    base_file = '../data/LEFAN1/train/run1_subject5.bvh'
    
    #model_name = 'base/stdiff_c1_l64_t5_r3_noang_anneal_0.pt'
    model_name = 'stdiff_c1_l64_t16.pt'
    
    flip = True if model_name == 'stdiff_c1_l64_t16.pt' else False

    model_path = '../models/{}'.format(model_name)
    
    model = torch.load(model_path)
    model.to(device)
    model.eval()

    data,_ = read_bvh(base_file, [3,4,7,8], 0, flip=flip)

    data = torch.tensor(data).to(device).float()
    condition = model.model.normalize(data[st_idx,:135])[None,...]
    
    for i in range(num_trial):
        out_path =  '../../bvh_demo/walk1_subject5_out_{}_'.format(st_idx)
        out_cnad = len(glob.glob(out_path+'*'))
        os.makedirs(out_path+str(out_cnad))
        out_file = out_path+str(out_cnad) 
        out_history, i = infer(model, condition, 1, num_steps) 

        if not optimize:
            np.savez('{}/{}.npz'.format(out_file,base_file), st_index=st_idx, st_file=base_file, motion=out_history)
            ik_x_to_outmot(out_history, 22, base_file, out_path, st_idx=st_idx, x_flip=False,optimize=False)
        else: 
            ik_x_to_outmot(out_history, 22, base_file, out_path, st_idx=st_idx, x_flip=False,optimize=True)
        #ik_x_to_outmot(out_history, 0, 22, base_file, out_file, st_idx=st_idx,  x_flip=flip)

def output_rl(npz_file, outpath, x_flip):
    if not os.path.isdir(outpath):
        os.makedirs(outpath)
    
    #base_file = '../data/LEFAN1/train/walk3_subject5.bvh'
    #joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time = load_joint_info(fn)
    f = np.load(npz_file, allow_pickle=True)
    
    base_file = str(f['st_file'])
    st_index = f['st_index']    
    out_history = f['motion']

    #frames,_ = read_bvh(base_file, foot_idx_lst=[3,4,7,8], root_idx=0, links=LEFAN1_links)
    #st_frame = frames[st_index:st_index+1]
    #st_frame = f['st_frame']
    
    ik_x_to_outmot(out_history, 0, 22, base_file, outpath, st_idx=st_index, x_flip=x_flip)



def pose_fix_LAFAN(base_file, motion_seqs, f_name_out, smooth_level):
    #fn = '../data/LEFAN1/all/run1_subject5.bvh'
    #fn = '../../bvh_output/walk3_subject5_out_100_2/out.bvh'
    joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time = load_joint_info(base_file)
    motion = load_motion_data(base_file)
    anchor_motion = motion[0]

    #output_bvh_from_bvh(outname, fn, motion, joint_name, joint_offset)
    #output_bvh_from_bvh('dance2_subject1_ik2.bvh', fn, motion, joint_name, joint_offset)
    
    anchor_motion[3:6]*=0
    new_offset, anchor_orientation = reform_norm_skel(anchor_motion, joint_offset, joint_name, joint_parent, joint_rot_order)
    new_motion = retarget_pose(anchor_orientation, motion_seqs, joint_parent, joint_rot_order)
    new_offset[0,:] *= 0

    new_motion = moving_average(new_motion,smooth_level)
    output_bvh_from_bvh(f_name_out, base_file, new_motion, joint_name, new_offset)

def euler_to_quat(euler_angle, order='ZYX'):
    return  R.from_euler(order, euler_angle, degrees=True).as_quat()

def quat_to_euler(quat, order='ZYX'):
    return  R.from_quat(quat).as_euler(order, degrees=True)

def euler_to_m6d(euler_angle, order='ZYX'):
    return  R.from_euler(order, euler_angle, degrees=True).as_matrix()[:2].flatten()

def m6d_to_euler(m6d, order='ZYX'):
    mat = np.zeros((3,3))
    a1 = m6d[:3] / np.linalg.norm(m6d[:3])
    a2 = m6d[3:6]
    a2 = a2-(a1*a2).sum()*a1
    a2 = a2 / np.linalg.norm(a2)
    a3 = np.cross(a1,a2)
    mat[0] = a1
    mat[1] = a2
    mat[2] = a3
    #print(mat)
    return  R.from_matrix(mat).as_euler(order, degrees=True)

def moving_average(motion, window_size, mode='6d'):
    num_seq, num_dim = motion.shape
    num_chn = num_dim // 3 -1

    shrink_size = window_size - 1
    
    if mode=='6d':
        mid_dim = 6
        euler_to_mid = euler_to_m6d
        mid_to_euler = m6d_to_euler

    elif mode=='quat':
        mid_dim = 4
        euler_to_mid = euler_to_quat
        mid_to_euler = m6d_to_euler

    motion_qrt = np.zeros((motion.shape[0],mid_dim*22+3))
    motion_qrt_out = np.zeros((motion.shape[0],mid_dim*22+3))

    motion_qrt[:,:3] = motion[:,:3]
    motion_out = np.zeros((motion.shape[0], num_dim))
    motion_out[:,:3] = motion[:,:3]
    for i in range(num_seq):
        for j in range(num_chn):
            input = motion[i,(3+3*j):(3+3*(j+1))]
            #print(euler_to_m6d(input))
            motion_qrt[i,(3+mid_dim*j):(3+mid_dim*(j+1))] = euler_to_mid(input)

    
    for j in range(motion_qrt.shape[-1]):
        window = np.ones(window_size) / window_size
        #print(motion_qrt[:,j].shape)
        motion_qrt_out[:,j] = np.convolve(motion_qrt[:,j], window, mode='same')
        
    for i in range(num_seq):
        for j in range(num_chn):
            quat = motion_qrt_out[i,(3+mid_dim*j):(3+mid_dim*(j+1))]
            #quat = quat/np.linalg.norm(quat)
            motion_out[i,(3+3*j):(3+3*(j+1))] = mid_to_euler(quat)
    return motion_out


def moving_average_1d(data, window_size):
    seq_len = data.shape[0]
    num_dim = data.shape[1]
    for j in range(num_dim):
        window = np.ones(window_size) / window_size
        #print(motion_qrt[:,j].shape)
        data[:,j] = np.convolve(data[:,j], window, mode='same')
    return data

def generate_keyframe_bvh(fn, fout_dir, frame_skip=20):
    joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time = load_joint_info(fn) 
    motion = load_motion_data(fn)
    
    frame_idxs = [i for i in range(0,motion.shape[0],frame_skip)]
    print(len(frame_idxs),'/',motion.shape[0])
    for i in range(len(frame_idxs)):
        idx = frame_idxs[i]
        motion_frame = [motion[idx]]
        f_name_out = os.path.join(fout_dir,str(i)+'.bvh')
        output_bvh_from_bvh(f_name_out, fn, motion_frame, joint_name, joint_offset)


def set_headrot_as_frame1(motion_seqs):
    motion_seqs[0,:] *= 0


def get_traj_bvh(file):
    outmotion = load_motion_data(file)
    xyz = outmotion[:,:3]
    xy = xyz[:,[0,2]]
    return xy


def get_flagtxt(file):
    eds = []
    with open(file) as f:
        lines = f.readlines()
        for line in lines:
            a,b = line.split(',')
            a = int(a)
            b = int(b)
            eds.append(b)
    return eds


def get_traj_x(x):
        
    def rot(yaw):
        cs = np.cos(yaw)
        sn = np.sin(yaw)
        return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])

    cur_pos = np.array([[0.0,0.0,0.0]])
    cum_x  = np.array([[0.0,0.0,0.0]])

    traj = np.zeros((x.shape[0],3))
    dr = x[:,2]
    yaws = np.cumsum(dr)
    yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)


    for i in range(1,x.shape[0]):
        
        cur_pos = np.zeros((1,3))
        cur_pos[0,0] = x[i,0]
        cur_pos[0,2] = x[i,1]
        cum_x += np.dot(cur_pos,rot(yaws[i]))
        traj[i,:] = copy.deepcopy(cum_x)
        #traj[i,:] = np.dot(x[i,:,],rot(yaws[i])) + copy.deepcopy(cur_pos)

    return traj[:,[0,2]]


if __name__=='__main__':
    '''
    generate_keyframe_bvh('../../bvh_demo/walk3_subject5_out_600_3/walk3_subject5_out_600_3_fix.bvh','../../bvh_demo/walk3_subject5_out_600_3/poster/')
    output_offline(st_idx=300, num_trial=1, num_steps=10)
    #motions = load_motion_data('../../bvh_demo/walk1_subject5_out_300_6/out.bvh')
    #pose_fix_LAFAN(motions, '../../bvh_demo/walk1_subject5_out_300_6/fixed.bvh', 3)
    '''
    
    f_path = '../../bvh_demo/raise_hand_release/1'
    in_path = '../../bvh_demo/raise_hand_release/1/out.npz'

    output_rl(in_path, f_path, x_flip=False)
    motions = load_motion_data(f_path+'/out.bvh')
    pose_fix_LAFAN(motions, f_path+'/fixed.bvh',3)
    
    '''
    file_lst = glob.glob('../../bvh_demo/*/out.bvh')
    smoothing_window = 4
    for f_name in file_lst:
        print(f_name)
        f_name_base = f_name.split('/')[-2]
        f_name_out = '../../bvh_demo/{}/{}_fix.bvh'.format(f_name_base, f_name_base)

        joint_name, joint_parent, joint_offset, joint_rot_order, joint_chn_num, frame_time = load_joint_info(f_name)
        motions = load_motion_data(f_name)
        pose_fix_LAFAN(motions, f_name_out, smoothing_window)
    '''

    '''
    rot_init = motion[0,3:]
    root_seq = motion[1:,:3]
    rotation_gt = motion[1:,3:]
    joints_seq = joints_seq[1:]
    rotation_pred = ik_progressive(rot_init, joints_seq[1:], bvh_info, max_iter=100, tol_change=0.0001)
    motion[1:,3:] = rotation_pred
     
    outname = 'dance2_fix.bvh'#'walk3_subject5_out_100_2_fix.bvh'
    output_bvh_from_bvh(outname, fn, new_motion, joint_name, new_offset)    
    '''