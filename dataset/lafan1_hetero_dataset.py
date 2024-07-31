import copy
import glob
import os.path as osp
import numpy as np
import torch

import dataset.lafan1_dataset as lafan1_dataset
import dataset.util.bvh as bvh_util
import dataset.util.geo as geo_util
import dataset.util.plot as plot_util

class LAFAN1_hetero(lafan1_dataset.LAFAN1):
    NAME = 'LAFAN1_hetero'
    def __init__(self, config):
        super().__init__(config)
        
    def process_data(self, fname):
        # read a single file, convert them into single format
        #if self.rpr_style == 'heterogeneous':
        final_x, motion_struct = bvh_util.read_bvh_hetero(fname, self.unit, self.fps, self.root_rot_offset)
        # use file num as label
        if self.data_trim_begin:
            final_x = final_x[self.data_trim_begin:]
        if self.data_trim_end:
            final_x = final_x[:self.data_trim_end]
        self.num_file += 1
        return final_x, motion_struct
    
    def load_new_data(self, path):
        x = self.process_data(path)
        x_normed = self.norm_data(x[0])
        #x_normed = self.transform_new_data(x_normed)
        return x_normed
    
    @staticmethod
    def get_heading_dr(data):
        heading_6d = data[:, 2:8]
        heading_rot = geo_util.m6d_to_rotmat(heading_6d)
        global_heading = torch.arctan2(heading_rot[:,0,2], heading_rot[:, 2,2]) 
        return global_heading
    
    @staticmethod
    def get_heading_from_val(data):
        heading_rot = geo_util.yaw_to_matrix(data)
        m6d = geo_util.rotation_matrix_to_6d(heading_rot)
        return torch.tensor(m6d)

    def transform_new_data(self, data):
        num_frame = data.shape[0]
        if self.data_component[0] == 'angle':
            data_piece = [data[...,:8],data[...,[9]]]
        else:
            data_piece = [data[...,:8]]
        for comp in self.data_component:
            if comp == 'position':
                data_piece.append(data[...,8:8+self.num_jnt*3])
             
            if comp == 'velocity':
                data_piece.append(data[...,8+self.num_jnt*3:8+self.num_jnt*6])

            if comp == 'angle':
                data_denormed = self.denorm_data(data)
                cur_data = data_denormed[...,8+self.num_jnt*6:8+self.num_jnt*12]
                cur_data = cur_data.reshape((num_frame, self.num_jnt, -1)).reshape(num_frame * self.num_jnt, -1) 
                cur_data = torch.tensor(cur_data)
                cur_data = self.from_6d_to_rpr(cur_data).numpy().reshape(num_frame, self.num_jnt,-1).reshape(num_frame, -1)
                data_piece.append(cur_data)
        return np.concatenate(data_piece,axis=-1)
    
    def transform_data_flattened(self, data, std, avg):
        num_frame = data.shape[0]
        self.joint_dim_lst = []
        self.vel_dim_lst = []
        self.angle_dim_lst = []
        self.dxdydr_dim_lst = [0,8]

        if self.data_component[0] == 'angle':
            data_piece = [data[...,:8],data[...,[9]]]
            std_piece = [std[...,:8],std[...,[9]]]
            avg_piece = [avg[...,:8],avg[...,[9]]]
            idx = 9
            self.height_index = 8
            
        else:
            data_piece = [data[...,:8]]
            std_piece = [std[...,:8]]
            avg_piece = [avg[...,:8]]
            idx = 8
            self.height_index = 9

        for comp in self.data_component:
            if comp == 'position':
                self.joint_dim_lst = [idx, idx+self.num_jnt*3]
                data_piece.append(data[...,idx:idx+self.num_jnt*3])
                std_piece.append(std[...,idx:idx+self.num_jnt*3])
                avg_piece.append(avg[...,idx:idx+self.num_jnt*3])
                idx += self.num_jnt*3

            if comp == 'velocity':
                self.vel_dim_lst = [idx, idx+self.num_jnt*3]
                data_piece.append(data[...,idx:idx+self.num_jnt*3])
                std_piece.append(std[...,idx:idx+self.num_jnt*3])
                avg_piece.append(avg[...,idx:idx+self.num_jnt*3])
                idx += self.num_jnt*3

            if comp == 'angle':
                data_denormed = self.denorm_data(data)
                cur_data = data_denormed[...,idx:idx+self.num_jnt*6]
                cur_data = cur_data.reshape((num_frame, self.num_jnt, -1)).reshape(num_frame * self.num_jnt, -1) 
                cur_data = torch.tensor(cur_data)

                cur_data = self.from_6d_to_rpr(cur_data).numpy().reshape(num_frame, self.num_jnt,-1).reshape(num_frame, -1)
                cur_data, normalization = self.create_norm(cur_data, 'zscore')
                self.angle_dim_lst = [idx, idx + self.num_jnt*self.data_rot_dim]
                new_std = normalization['std']
                new_avg = normalization['avg']
                std_piece.append(new_std)
                avg_piece.append(new_avg)
                data_piece.append(cur_data)
                idx += self.num_jnt*self.data_rot_dim

        return np.concatenate(data_piece,axis=-1), np.concatenate(std_piece,axis=-1), np.concatenate(avg_piece,axis=-1)

    

    def get_dim_by_key(self, category, key):
        if category == "heading":
            rt = [2,8]

        elif category == "root_dxdy":
            rt = [0,2]
        
        elif category == "position":
            index_offset = self.joint_dim_lst[0] 
            index_key = self.joint_names.index(key)
            rt =  [index_offset + index_key*3, index_offset+index_key*3+3]

        elif category == "velocity":
            index_offset = self.vel_dim_lst[0] 
            index_key = self.joint_names.index(key) 
            rt = [index_offset + index_key*3, index_offset+index_key*3+3]

        elif category == "angle":
            index_offset = self.angle_dim_lst[0] 
            index_key = self.joint_names.index(key)
            rt = [index_offset + index_key*self.data_rot_dim, index_offset + index_key*self.data_rot_dim + self.data_rot_dim]
        return rt
    
    def x_to_rotation(self, x, mode):
        dxdy = x[...,:2] 
        dr = geo_util.rotation_6d_to_matrix(x[...,2:8])
        dr, _ = geo_util.sepr_rot_heading(dr)

        nframe = dxdy.shape[0]
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        
        rot_headings = np.zeros((dxdy.shape[0],3,3))
        rot_headings[0] = np.eye(3)
        for i in range(1, nframe):
            cur_pos = np.zeros((1,3))
            cur_pos[0,0] = dxdy[i,0]
            cur_pos[0,2] = dxdy[i,1]
            dpm_lst[i,:] = copy.deepcopy(dpm)
            cur_rot = np.dot(rot_headings[i-1],dr[i])

            dpm += np.dot(cur_pos, cur_rot)
            rot_headings[i,:] = copy.deepcopy(cur_rot)
            
        if mode == 'position':
            rotation_0 = x[0, self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            rotation = self.ik_seq_slow(x[0], x[1:])
            rotation_0 = rotation_0.reshape((-1, self.num_jnt, self.data_rot_dim))
            rotation = np.concatenate([rotation_0, rotation], axis = 0)
        
        elif mode == 'angle':
            rotation = x[..., self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            rotation = rotation.reshape((-1, self.num_jnt, self.data_rot_dim))

        elif mode == 'velocity':
            rotation_0 = x[0, self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            jnts = self.vel_step_seq(x)
            x[...,self.joint_dim_lst[0]:self.joint_dim_lst[1]] = jnts.view(x.shape[0],-1)
            rotation = self.ik_seq_slow(x[0],x[1:])
            rotation = np.concatenate([rotation_0, rotation], axis = 0)

        
        rotation = self.from_rpr_to_rotmat(torch.tensor(rotation)).cpu().numpy()
        
        rotation[:,0,...] = np.matmul(rot_headings.transpose(0,2,1),rotation[:,0,...])
        rotation = geo_util.rotation_matrix_to_euler(rotation, self.rotate_order)/np.pi*180
        
        dpm_lst[:,1] = x[...,self.height_index]
        return dpm_lst, rotation
    
    def x_to_jnts(self, x, mode):
        dxdy = x[...,:2] 
        dr = geo_util.rotation_6d_to_matrix(x[...,2:8])
        dr, _ = geo_util.sepr_rot_heading(dr)
        #ang_frames[:, self.data_rot_dim*i: self.data_rot_dim*i+self.data_rot_dim]
        
        if mode == 'angle':
            jnts = self.fk_local_seq(x) 
        elif mode == 'position':
            x[..., [self.joint_dim_lst[0],self.joint_dim_lst[0]+2]] *= 0
            jnts = self.jnts_step_seq(x)
        elif mode == 'velocity':
            x[..., [self.joint_dim_lst[0],self.joint_dim_lst[0]+2]] *= 0
            x[..., [self.vel_dim_lst[0],self.vel_dim_lst[0]+2]] *= 0
            jnts = self.vel_step_seq(x)
        elif mode == 'ik_fk':
            rotations = self.ik_seq_slow(x[0],x[1:])
            x[1:, self.angle_dim_lst[0]:self.angle_dim_lst[1]] = rotations.reshape(-1,self.data_rot_dim*self.num_jnt)
            jnts = self.fk_local_seq(x)
        #return jnts
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))

        rot_headings = np.zeros((dxdy.shape[0],3,3))
        rot_headings[0] = np.eye(3)
        for i in range(1, jnts.shape[0]):
            cur_pos = np.zeros((1,3))
            cur_pos[0,0] = dxdy[i,0]
            cur_pos[0,2] = dxdy[i,1]
            cur_rot = np.dot(rot_headings[i-1],dr[i])

            dpm += np.dot(cur_pos, cur_rot)
            dpm_lst[i,:] = copy.deepcopy(dpm)
            rot_headings[i] = copy.deepcopy(cur_rot)
            jnts[i,:,:] = np.dot(jnts[i,:,:], cur_rot) + copy.deepcopy(dpm)
        return jnts
        
    def x_to_trajs(self,x):
        dxdy = x[...,:2] 
        dr = geo_util.rotation_6d_to_matrix(x[...,2:8])
        dr, _ = geo_util.sepr_rot_heading(dr)
        #jnts = np.reshape(x[...,3:69],(-1,self.num_jnt,3))
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        rot_headings = np.zeros((dxdy.shape[0],3,3))
        rot_headings[0] = np.eye(3)
        for i in range(1, x.shape[0]):
           cur_pos = np.zeros((1,3))
           cur_pos[0,0] = dxdy[i,0]
           cur_pos[0,2] = dxdy[i,1]
           cur_rot = np.dot(rot_headings[i-1],dr[i])
           dpm += np.dot(cur_pos,cur_rot)
           rot_headings[i] = copy.deepcopy(cur_rot)
           dpm_lst[i,:] = copy.deepcopy(dpm)
        return dpm_lst[...,[0,2]]
    

    def get_motion_fpaths(self):
        return glob.glob(osp.join(self.path, '*.{}'.format('bvh')))
    
    def plot_jnts_only(self, x):
        return plot_util.plot_lafan1(x,links=self.links)

    def plot_jnts(self, x, path=None):
        return plot_util.plot_multiple(x, self.links, plot_util.plot_lafan1, self.fps, path)
        
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)