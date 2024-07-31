import dataset.util.geo as geo_util
import dataset.util.skeleton_info as skel_dict

import numpy as np
import copy
import torch
import math
import dataset.util.motion_struct as motion_struct

SMPL_JOINTS = {'hips' : 0, 'leftUpLeg' : 1, 'rightUpLeg' : 2, 'spine' : 3, 'leftLeg' : 4, 'rightLeg' : 5,
                'spine1' : 6, 'leftFoot' : 7, 'rightFoot' : 8, 'spine2' : 9, 'leftToeBase' : 10, 'rightToeBase' : 11, 
                'neck' : 12, 'leftShoulder' : 13, 'rightShoulder' : 14, 'head' : 15, 'leftArm' : 16, 'rightArm' : 17,
                'leftForeArm' : 18, 'rightForeArm' : 19, 'leftHand' : 20, 'rightHand' : 21}

NUM_KEYPT_VERTS = 43

def get_parent_from_link(links):
    max_index = -1
    parents_dict = dict()
    parents = list()
    for pair in links:
        st, ed = pair
        if st>ed:
            st, ed = ed, st
            #print(st,ed,max_index)
        max_index = ed if ed>max_index else max_index
        parents_dict[ed] = st
    parents_dict[0] = -1
    for i in range(max_index+1):
        parents.append(parents_dict[i])
    return parents

def load_amass_file(amass_file, root_idx=0):
    motion_frame = np.load(amass_file)

    fps = motion_frame['fps']
    gender = motion_frame['gender']
    floor_height = motion_frame['floor_height']
    contacts  = motion_frame['contacts']
    trans = motion_frame['trans']
        
    root_orient = motion_frame['root_orient']
    pose_body = motion_frame['pose_body']
    betas = motion_frame['betas']
    joints = motion_frame['joints']
    joints_vel = motion_frame['joints_vel']

    len_seq = root_orient.shape[0]
    root_heights = copy.deepcopy(joints[:,[0],2])
    headings_angle = np.zeros((len_seq))
    headings_rot = np.zeros((len_seq,3,3))
    skel_pos_vel = np.zeros((len_seq,22,3))
    
    root_orient = torch.tensor(root_orient)
    joints = torch.tensor(joints)
    pose_body = torch.tensor(pose_body).view(pose_body.shape[0],-1,3)
    len_jnt_body = pose_body.shape[1]

    quaternion_offset = torch.tensor([[math.sin(-math.pi/4), 0, 0, math.cos(-math.pi/4)]]).expand(root_orient.shape[0],-1)
    
    # Create the quaternion
    root_orient_quat = geo_util.exp_map_to_quat(root_orient).float()
    
    
    root_orient_quat_z = geo_util.sepr_z_quat(root_orient_quat)
    root_orient_quat_z_inv = geo_util.quat_conjugate(root_orient_quat_z)

    root_orient_quat_xy = geo_util.quat_mul(root_orient_quat_z_inv, root_orient_quat)
    root_orient_quat_xy = geo_util.quat_mul(quaternion_offset, root_orient_quat_xy)

    root_orient_xy = geo_util.quat_to_6d(root_orient_quat_xy)

    pose_body = torch.cat([geo_util.quat_to_6d(geo_util.exp_map_to_quat(pose_body[:,i,:])) for i in range(len_jnt_body)],dim=1)
    
    root_drot_quat_z = geo_util.quat_mul(root_orient_quat_z[..., :-1, :], geo_util.quat_conjugate(root_orient_quat_z[..., 1:, :]))
    root_drot_angle_z = geo_util.sepr_z_angle(root_drot_quat_z)

    links = skel_dict.skel_dict['AMASS']['links']
    
    root_dxdydz = joints[1:, root_idx,:]- joints[:-1, root_idx,:]
    root_dxdydz[:, 2] *= 0

    joints[:,:,:2] = joints[:,:,:2] - joints[:,[root_idx],:2]

    root_dxdydz = geo_util.quat_rotate(root_orient_quat_z_inv[1:], root_dxdydz)
    root_dxdydz =  geo_util.quat_rotate(quaternion_offset[1:], root_dxdydz)
    root_dxdy = root_dxdydz[..., [0,2]]

    for i_jnt in range(joints.shape[1]):
        joint_no_heading = geo_util.quat_rotate(root_orient_quat_z_inv, joints[:,i_jnt,:])
        joints[:,i_jnt,:] = geo_util.quat_rotate(quaternion_offset, joint_no_heading)
        
    joints_vel = joints[1:,...] - joints[:-1,...] 
    
    xs = np.concatenate([root_dxdy.reshape(root_dxdy.shape[0],-1), 
                        root_drot_angle_z.reshape(root_drot_angle_z.shape[0],-1), 
                        joints[1:].reshape(joints_vel.shape[0],-1), 
                        joints_vel.reshape(joints_vel.shape[0],-1), 
                        root_orient_xy[1:].reshape(root_dxdy.shape[0],-1),
                        pose_body[1:].reshape(root_dxdy.shape[0],-1)],axis=-1)  
    return xs

def init_motion_from_offset(offset, links, names):
    links_parent = get_parent_from_link(links)
    skeleton = motion_struct.Skeleton()
    joint_lst = []
    for i in range(len(names)):
        joint = motion_struct.Joint(names[i],idx=i)
        joint.set_offset(offset[i])
        
        if links_parent[i] != -1:
            joint.add_parent(joint_lst[links_parent[i]])
            joint._parent_joint.add_child(i)
        else:
            skeleton.set_root(joint)
        joint_lst.append(joint)
        skeleton.add_joint(joint)
    motion = motion_struct.Motion(skeleton)
    return motion

def init_motion_from_amass(amass_file):
    motion_frame = np.load(amass_file)
    skeleton_offset, betas = retrieve_offset(motion_frame)
    
    #skeleton_offset = motion_frame
    skeleton_offset_mean = skeleton_offset.mean(axis=0)
    skeleton_offset_std = skeleton_offset.std(axis=0)
    
    links = skel_dict.skel_dict['AMASS']['links']
    names = skel_dict.skel_dict['AMASS']['name_joint']
    
    motion = init_motion_from_offset(skeleton_offset_mean, links, names)
    return motion


def fk(motion_frame, joint_offset):
    joints = torch.tensor(motion_frame['joints'])
    dtype = joints.dtype
    num_jnt = joints.shape[1]
    num_frames = joints.shape[0]
    joint_positions = torch.zeros(num_frames, num_jnt, 3).float()
    joint_orientations = torch.zeros(num_frames, num_jnt, 3, 3).float()
    joint_translation = torch.zeros(num_frames, num_jnt, 3, 3)
    
    #joint_offset = torch.tensor(skel_dict.skel_dict['AMASS']['offset_joint'])
    root_rots_expmap = torch.tensor(motion_frame['root_orient'])
    rots_expmap = torch.tensor(motion_frame['pose_body'])
    betas =  motion_frame['betas']
    joint_parent = get_parent_from_link(skel_dict.skel_dict['AMASS']['links'])
    for i in range(num_jnt):
        
        if joint_parent[i] == -1: #root
            local_rotation = geo_util.exp_map_to_quat(root_rots_expmap) 
            local_rotation = geo_util.quat_to_rotmat(local_rotation)
            #local_rotation = geo_util.rotmat_to_quat(local_rotation)
            joint_orientations[:,i] = local_rotation
        else:
            idx = i-1
            local_rotation = geo_util.exp_map_to_quat(rots_expmap[:, 3*idx: 3*idx+3])
            local_rotation = geo_util.quat_to_rotmat(local_rotation).float()
            
            joint_orientations[:,i] = joint_orientations[:,joint_parent[i]] @ local_rotation
            #joint_positions[:,i] = joint_positions[:,joint_parent[i]] + torch.matmul(joint_offset[i].expand(joint_orientations.shape[0],-1)[...,None,:], geo_util.quat_to_rotmat(joint_orientations[:,joint_parent[i]])).squeeze(1)
            joint_positions[:,i] = joint_positions[:,joint_parent[i]] + (joint_orientations[:,joint_parent[i]] @ joint_offset[i].expand(joint_orientations.shape[0],-1)[...,None]).squeeze(-1)
    
    joint_positions += joints[..., [0], :] #height
    return joint_positions

def get_glb_skeleton_offset(joint_parent, joint_offset):
    joint_glb_pos = torch.zeros(joint_offset.shape[-2], 3).float()
    for i in range(len(joint_parent)):
        if joint_parent[i] == -1:
            continue
        joint_glb_pos[i] = joint_glb_pos[joint_parent[i]] +  joint_offset[i]
    return joint_glb_pos

def retrieve_offset(motion_frame):
    joint_positions = torch.tensor(motion_frame['joints'])
    num_jnt = joint_positions.shape[1]
    num_frames = joint_positions.shape[0]
    joint_rotations = torch.zeros(num_frames, num_jnt, 4).float()
    joint_orientations = torch.zeros(num_frames, num_jnt, 4).float()
    joint_orientations_inv = torch.zeros(num_frames, num_jnt, 4)
    
    joint_offset = torch.zeros(num_frames, num_jnt, 3).float()
    root_rots_expmap = torch.tensor(motion_frame['root_orient'])
    rots_expmap = torch.tensor(motion_frame['pose_body'])
    
    betas =  motion_frame['betas']
    joint_parent = get_parent_from_link(skel_dict.skel_dict['AMASS']['links'])
    
    for i in range(num_jnt):
        if joint_parent[i] == -1: #root
            local_rotation = geo_util.exp_map_to_quat(root_rots_expmap) 
            joint_orientations[:,i] = local_rotation
        else:
            idx = i-1
            local_rotation = geo_util.exp_map_to_quat(rots_expmap[:, 3*idx: 3*idx+3])                
            joint_orientations[:,i] = geo_util.quat_mul(joint_orientations[:,joint_parent[i]], local_rotation)
            inv_ori = geo_util.quat_conjugate(joint_orientations[:,joint_parent[i]])
            trans = joint_positions[:,i]-joint_positions[:,joint_parent[i]]
            joint_offset[:,i] = geo_util.quat_rotate(inv_ori, trans)
           
    
    return joint_offset.cpu().detach().numpy(), betas


def extract_sk_lengths(positions, linked_joints):
    #position: NxJx3
    #single frame rigid body restriction
    lengths = np.zeros((len(linked_joints),positions.shape[0]))
    for i,(st,ed) in enumerate(linked_joints):
        length =  np.linalg.norm(positions[:,st] - positions[:,ed], axis=-1)     
        lengths[i] = length
    return np.mean(lengths,axis=-1)


def export_smpl_file(betas, body_model, motion, offset_translate=None, offset_rotate=None):
    '''
    Given x_pred_dict from the model rollout and the ground truth dict, runs through SMPL model to visualize
    '''
    J = len(SMPL_JOINTS)
    V = NUM_KEYPT_VERTS

    root_xyzs = motion._positions[:,0,:]
    rotations = motion._rotations
    
    rotations_aa = geo_util.rotmat_to_exp_map(torch.from_numpy(rotations).view(-1,3,3))
    root_rotation_aa, joint_rotation_aa = rotations_aa[:,0],  rotations_aa[:,1:]

    if offset_translate is not None:
        root_xyzs[:,0] += offset_translate[0]
        root_xyzs[:,2] += offset_translate[1]
    if offset_rotate is not None:
        #TODO
        pass
    
    body_pred = body_model(pose_body=joint_rotation_aa, 
                    pose_hand=None,
                    betas=betas,
                    root_orient=root_rotation_aa,
                    trans=root_xyzs)

    pred_smpl_joints = body_pred.Jtr[:, :J]
    
