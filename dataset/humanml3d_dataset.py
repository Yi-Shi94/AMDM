
import glob
import numpy as np

import dataset.base_dataset as base_dataset
import dataset.util.amass as amass_util
import dataset.util.plot as plot_util
import dataset.util.geo as geo_util
import os.path as osp
import codecs as cs

def text_parse(text_file, dataset_name):
    # return all texts in a single file as a list
    text_data = []
    if dataset_name.lower() == 'humanml3d':
        fps = 20
        with cs.open(text_file) as f:
            for line in f.readlines():
                text_dict = {}
                line_split = line.strip().split('#')
                caption = line_split[0]
                tokens = line_split[1].split(' ')

                f_tag = float(line_split[2])
                to_tag = float(line_split[3])
                f_tag = 0.0 if np.isnan(f_tag) else f_tag
                to_tag = 0.0 if np.isnan(to_tag) else to_tag

                text_dict['caption'] = caption
                text_dict['tokens'] = tokens
                
                if f_tag == 0.0 and to_tag == 0.0:
                    text_dict['f_idx'] = 0
                    text_dict['to_idx'] = -1
                    
                else:
                    text_dict['f_idx'] = int(f_tag * fps) 
                    text_dict['to_idx'] = int(to_tag * fps)
                
                text_data.append(text_dict)

    elif dataset_name.lower() == 'kit':
        fps = 20
        raise NotImplementedError('must be in [humanml3d]')
    else:
        fps = 30
        raise NotImplementedError('must be in [kit,humanml3d]')
    return text_data


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

def retrieve_offset_(positions, links):
    positions_first = positions[0]
    kit_raw_offsets = np.array(
    [
        [0, 0, 0],
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
        [1, 0, 0],
        [0, -1, 0],
        [0, -1, 0],
        [-1, 0, 0],
        [0, -1, 0],
        [0, -1, 0],
        [1, 0, 0],
        [0, -1, 0],
        [0, -1, 0],
        [0, 0, 1],
        [0, 0, 1],
        [-1, 0, 0],
        [0, -1, 0],
        [0, -1, 0],
        [0, 0, 1],
        [0, 0, 1]
    ]
)

    t2m_raw_offsets = np.array([[0,0,0],
                           [1,0,0],
                           [-1,0,0],
                           [0,1,0],
                           [0,-1,0],
                           [0,-1,0],
                           [0,1,0],
                           [0,-1,0],
                           [0,-1,0],
                           [0,1,0],
                           [0,0,1],
                           [0,0,1],
                           [0,1,0],
                           [1,0,0],
                           [-1,0,0],
                           [0,0,1],
                           [0,-1,0],
                           [0,-1,0],
                           [0,-1,0],
                           [0,-1,0],
                           [0,-1,0],
                           [0,-1,0]]) * 1.0
    
    parents = get_parent_from_link(links)
    for i in range(1, t2m_raw_offsets.shape[0]):
        t2m_raw_offsets[i] = np.linalg.norm(positions_first[i] - positions_first[parents[i]], ord=2, axis=0) * t2m_raw_offsets[i]
    return kit_raw_offsets



def retrieve_offset(local_rotations, joint_positions, links):
    """     joint_positions = torch.tensor(motion_frame['joints'])
    dtype = joint_positions.dtype
    num_jnt = joint_positions.shape[1]
    num_frames = joint_positions.shape[0]
    
    root_rots_expmap = torch.tensor(motion_frame['root_orient'])
    rots_expmap = torch.tensor(motion_frame['pose_body']) """
    num_frames = joint_positions.shape[0]
    num_jnt = 22
    joint_offset = np.zeros((num_frames, num_jnt, 3))
    joint_orientations = np.zeros((num_frames, num_jnt, 3, 3))
    joint_orientations[:,0] = np.eye(3) 
    #joint_orientations_inv = torch.zeros(num_frames, num_jnt, 4)
    joint_parent = get_parent_from_link(links)
    #joint_positions = joint_positions).float()
    #local_rotations = torch.from_numpy(local_rotations).float()
    
    for i in range(num_jnt):
        if i == 0:
            continue
        idx = i-1
        idx_parent = joint_parent[i]-1
        local_rotation = local_rotations[:,idx]
        local_rotation = geo_util.rotation_6d_to_matrix(local_rotation)
        
        joint_orientations[:,i] = np.matmul(joint_orientations[:,joint_parent[i]], local_rotation)
        #joint_positions[:,i] = joint_joint_positionspositions[:,joint_parent[i]] + geo_util.quat_rotate(joint_orientations[:,joint_parent[i]], joint_offset[i])
        #joint_orientations_inv[:, i] = geo_util.quat_conjugate(joint_orientations[:,i])
        inv_ori = np.transpose(joint_orientations[:,joint_parent[i]], (0,2,1))
        trans = joint_positions[:,i] - joint_positions[:,joint_parent[i]]
        print(inv_ori.shape, trans.shape)
        joint_offset[:,i] = np.matmul(inv_ori, trans[...,None]).squeeze(-1)
    return joint_offset


def fk(rot_root, rot_joints, joint_offset, root_xyz, links):
    num_frames = rot_root.shape[0]
    num_jnt = joint_offset.shape[0]
   
    joint_offset = joint_offset[None,...].repeat(num_frames,axis=0)
    
    joint_positions = np.zeros((num_frames, num_jnt, 3))
    joint_orientations =  np.zeros((num_frames, num_jnt, 3, 3))
    joint_orientations[:,0] = np.eye(3)

    joint_parent = get_parent_from_link(links)
    for i in range(1,num_jnt):
        idx = i-1
        local_rotation = rot_joints[:,idx]
        local_rotation = geo_util.rotation_6d_to_matrix(local_rotation)#.float()
        print(local_rotation.shape, joint_orientations[:,joint_parent[i]].shape)
        joint_orientations[:,i] = joint_orientations[:,joint_parent[i]] @ local_rotation
        #joint_positions[:,i] = joint_positions[:,joint_parent[i]] + torch.matmul(joint_offset[i].expand(joint_orientations.shape[0],-1)[...,None,:], geo_util.quat_to_rotmat(joint_orientations[:,joint_parent[i]])).squeeze(1)
        print(joint_orientations[:,joint_parent[i]].shape,  joint_offset[:,i, None].shape)
        joint_positions[:,i] = joint_positions[:,joint_parent[i]] + (joint_orientations[:,joint_parent[i]] @ joint_offset[:,i, ..., None]).squeeze(-1)

    #joint_positions += root_xyz[:,None,:] #joints[..., [0], :] #height
    return joint_positions



class HumanML3D(base_dataset.BaseMotionData):
    NAME = 'HumanML3D_AR'
    def __init__(self, config):
        super().__init__(config)
        self.use_cond = False
        self.available_form = ['joint', 'vel']

    def plot_jnts_singe(self, x):
        return plot_util.plot_lafan1(x, self.links, plot_util.plot_lafan1, self.fps, None)

    def plot_jnts(self, x, path=None):
        return plot_util.plot_jnt_vel(x, self.links, plot_util.plot_lafan1, self.fps, path)
        
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)
    
    def get_motion_fpaths(self):
        path =  osp.join(self.path,'*.{}'.format('npy'))
        file_lst = glob.glob(path, recursive = True)
        return file_lst
    
    def process_data(self, pos_fname):
        path = osp.dirname(osp.dirname(pos_fname))
        jnt_fname = osp.join(path, 'new_joints', '000021.npy')
        vec_fname = osp.join(path, 'new_joint_vecs', '000021.npy')

        joint_pos_final = np.load(jnt_fname)
        joint_vecs = np.load(vec_fname)
        nframe, njoint, _ = joint_pos_final.shape

        links = np.array(self.links)
        names = self.joint_names
        plot_util.plot_lafan1(joint_pos_final, links)
        
        joint_pos_feat = joint_vecs[:,4:4+21*3].reshape(joint_vecs.shape[0],21,3)
        root_xyz = np.zeros((joint_pos_feat.shape[0],1,3)) 
        root_xyz[...,1] = joint_vecs[:,3:4]
        joint_pos = np.concatenate([root_xyz, joint_pos_feat], axis=1)
        plot_util.plot_lafan1(joint_pos, self.links)
        
        root_rot_rad = -2 * np.cumsum(joint_vecs[:,0])
        root_rot_rad = root_rot_rad - (root_rot_rad//(np.pi*2))*(np.pi*2)
        root_heading_mat = np.array([geo_util.rot_yaw(root_rot_rad[i]) for i in range(root_rot_rad.shape[0])])
        root_heading_mat_inv = geo_util.rotation_matrix_to_6d(root_heading_mat.transpose(0,2,1))
        joint_pos = np.matmul(np.repeat(root_heading_mat[:, None,:, :], njoint, axis=1), joint_pos[...,None]).squeeze(-1)
        plot_util.plot_lafan1(joint_pos, links)
        
        #############
        dxdy = joint_vecs[:, 1:3]
        dxdydz = np.zeros((joint_vecs.shape[0], 3, 1))
        dxdydz[:,[0,2],:] = dxdy[...,None]
        dxdydz = np.matmul(root_heading_mat, dxdydz).squeeze(-1)
        root_xyz = np.cumsum(dxdydz, axis=0)
        #joint_pos = np.matmul(np.repeat(root_heading_mat[:, None,:, :], njoint, axis=1), joint_pos[...,None]).squeeze(-1)
        joint_pos += root_xyz[:,None,:]
        plot_util.plot_lafan1(joint_pos, self.links)
        ##############
        
        rotation_local = joint_vecs[:,67:67+21*6].reshape(joint_vecs.shape[0],21,6)
        #joint_pos_local = #joint_vecs[:,4:4+21*3].reshape(joint_vecs.shape[0],21,3)

        skeleton_offset = retrieve_offset_(joint_pos_final, links)
        #skeleton_offset_mean = skeleton_offset.mean(axis=0)
        #skeleton_offset_std = skeleton_offset.std(axis=0)
       
        joint_parent = get_parent_from_link(self.links)
        glb_offset = np.zeros((22, 3))
        
        for i in range(skeleton_offset.shape[0]):
            i_parent = joint_parent[i]
            if i == 0:
                glb_offset[i] = skeleton_offset[i]
            else:
                glb_offset[i] += glb_offset[i_parent] + skeleton_offset[i]
        
        glb_offset = glb_offset[None,...]
        plot_util.plot_lafan1(glb_offset, self.links) 
        
        motion_struct = amass_util.init_motion_from_offset(skeleton_offset, links, names)
        positions = fk(root_heading_mat, rotation_local, skeleton_offset, root_xyz, links)
        plot_util.plot_lafan1(positions, self.links)

        root_linear_vel = np.zeros((joint_vecs.shape[0],3))
        root_linear_vel[:,[0,2]] = joint_vecs[:,1:3]
       
        root_linear_vel_glob = np.matmul(root_heading_mat, root_linear_vel[...,None])
        root_pos = np.cumsum(root_linear_vel_glob, axis=0)
        

        joint_pos -= root_pos.reshape(root_pos.shape[0],1,-1)
        #print(root_heading.shape, root_heading_inv_mat.shape)
        plot_util.plot_lafan1(joint_pos, self.links)


        return    

    def __len__(self):
        return len(self.valid_idx)

    def __getitem__(self, idx):
        idx_ = self.valid_idx[idx]
        motion = self.motion_flattened[idx_:idx_+self.rollout]
        return  motion


if __name__=='__main__':
    pass
