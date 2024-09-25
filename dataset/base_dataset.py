import os.path as osp
import numpy as np
import torch
import torch.optim as optim
import torch.utils.data as data
import tqdm
import math
import copy
import dataset.util.plot as plot_util
from dataset.util.skeleton_info import skel_dict
import dataset.util.unit as unit_util
import dataset.util.bvh as bvh_util
import dataset.util.geo as geo_util

class BaseMotionData(data.Dataset):
    # For a directory contains multiple identical file type
    def __init__(self, config):
        
        self.dataset_name = config["data"]["dataset_name"]
        
        if self.dataset_name in skel_dict:
            self.skel_info = skel_dict[self.dataset_name]
        elif self.dataset_name.split('_')[0] in skel_dict:
            self.skel_info = skel_dict[self.dataset_name.split('_')[0]]
        
        self.use_eval_split = False
        self.links = self.skel_info.get("links",None)
        self.joint_names = self.skel_info.get("name_joint",None)
        self.end_eff = self.skel_info.get("end_eff",None)
        self.joint_offset = self.skel_info.get("offset_joint",None)

        self.root_idx = self.skel_info.get("root_idx",None)
        self.foot_idx = self.skel_info.get('foot_idx',None)
        self.toe_idx = self.skel_info.get('toe_idx',None)
        self.unit = self.skel_info.get('unit',None)
        self.rotate_order = self.skel_info.get('euler_rotate_order',None)
        
        self.fps = config["data"]["data_fps"]

        self.path = config["data"]["path"]

        self.min_motion_len = config["data"]["min_motion_len"]
        self.max_motion_len = config["data"]["max_motion_len"]
        self.data_trim_begin = config["data"]["data_trim_begin"]
        self.data_trim_end = config["data"]["data_trim_end"]

        self.root_rot_offset = config["data"]["root_rot_offset"]
        
        # if true, load data, if not only load stats for normalization(std avg)
        self.load_full_data = config["data"].get('load_full_data',True)

        # if true, when loading data, load cached data.npz, if not load motion file directly
        self.load_cache = config["data"].get('load_cache',True)

        self.data_rot_rpr = config["data"].get("data_rot_rpr","6d") #6d, expmap, aa, quat
        self.data_root_rot_rpr = config["data"].get("data_root_rot_rpr","angle") # angle, rot
        self.data_root_linear_rpr = config["data"].get("data_root_linear_rpr","dxdy") #dxdy, dxdydz, aa, quat

        self.rollout = config["optimizer"]["rollout"]
        self.use_cond = config["model_hyperparam"]["use_cond"]

        self.test_num_init_frame = config["test"]["test_num_init_frame"]
        self.test_num_steps = config["test"]["test_num_steps"]

        rot_dim_map = {"6d":6, "expmap":3, "aa":3, "quat":4}
        self.data_rot_dim = rot_dim_map[self.data_rot_rpr]
       
        root_rotation_dim_map = {"rot":self.data_rot_dim, "angle":1}
        self.data_root_rot_dim = root_rotation_dim_map[self.data_root_rot_rpr]

        root_linear_dim_map = {"dxdy":2, "dxdydz":3}
        self.data_root_linear_dim = root_linear_dim_map[self.data_root_linear_rpr]
        
        self.data_root_dim = 0 #self.data_root_rot_dim + self.data_root_linear_dim
        self.dxdydr_dim_lst = [0,0]
        self.joint_dim_lst =  [0,0]
        self.vel_dim_lst = [0,0]
        self.angle_dim_lst = [0,0]
        self.offset_dim_lst = [0,0]
        self.height_index = [0,0]

        #self.data_format = config["data"].get("data_format",["dxdyda","position","velocity","angle"])
        self.data_component = config["data"]["data_component"] #,["position","velocity","angle"])
        
        self.use_offset = True if "offset" in self.data_component else False 
        self.num_file = 0
        self.file_lst = []
        
        self.extra = dict() # for labels and other multi-modal data (text & audio & video)
        #self.labels = list()

        self.motion_flattened = list()
        self.labels = list() # for labels and other multi-modal data (text & audio & video)
        
        self.valid_idx = []
        self.valid_range = list()
        self.test_valid_idx = list()    
        self.file_lst = list()
        self.joint_offset = list()
        self.test_ref_clips = list()  

        if osp.exists(osp.join(self.path,'stats.npz')):
            with np.load(osp.join(self.path,'stats.npz')) as stats:

                self.std = stats['std']
                self.avg = stats['avg']

                self.normalization = {
                    'mode': 'zscore',
                    'std': self.std,
                    'avg': self.avg
                }
                
                self.data_root_dim = stats['data_root_dim']
                self.dxdydr_dim_lst = stats['dxdydr_dim_lst'] 
                self.joint_dim_lst = stats['joint_dim_lst']  
                self.vel_dim_lst = stats['vel_dim_lst']
                self.angle_dim_lst = stats['angle_dim_lst']
                self.offset_dim_lst = stats['offset_dim_lst']
                self.height_index = stats['height_index']

                self.joint_names = stats['joint_names'].tolist()
                self.joint_offset = stats['joint_offset']
                self.num_jnt = len(self.joint_names)

                self.links = stats['links']
                self.frame_dim = stats['frame_dim']

        if self.load_full_data:
            if osp.exists(osp.join(self.path,'data.npz')) and self.load_cache:
                with np.load(osp.join(self.path,'data.npz')) as data:
                    self.motion_flattened = data['motion_flattened']
                    self.valid_range = data['valid_range']
                    self.file_lst = data['file_lst']
                
                if 'labels' in data.keys():
                    self.labels= data['labels']
                
            else:
                file_paths = self.get_motion_fpaths()
                
                self.total_len = 0
                self.motion_struct = None
                
                for i, fname in enumerate(tqdm.tqdm(file_paths)):
                    ret = self.process_data(fname)
                    if ret is None:
                        print('Error loading file:{}'.format(fname))
                        continue
                    
                    elif type(ret) is not tuple:
                        motion = ret

                    else:
                        # first instance must be motion and second instance must be motion class
                        motion = ret[0]
                        motion_struct = ret[1]

                        # skeleton struct class not defined
                        if self.motion_struct is None:
                            self.motion_struct = motion_struct
                        
                        # when not using offset in feature, we define a universal joint offset for all motions
                        if not self.use_offset:
                            self.joint_offset =  motion_struct._skeleton.get_joint_offset()
                        
                        # when using offset in feature, we record offset for each motion
                        else:
                            offset = motion_struct._skeleton.get_joint_offset()
                            self.joint_offset.append(offset)

                    length = len(motion)

                    if self.min_motion_len and length < self.min_motion_len:
                        continue
                    if self.max_motion_len != -1 and length > self.max_motion_len:
                        continue

                    if self.use_cond:
                        self.labels.extend(self.process_label(fname))

                    self.file_lst.append(fname)
                    
                    self.valid_range.append([self.total_len, self.total_len + length])
                    
                    self.total_len += length
                    self.motion_flattened.append(motion)

                # Num frames x Dim feature
                self.motion_flattened = np.concatenate(self.motion_flattened,axis=0)
                
                # skeleton joint offset
                self.joint_offset = np.array(self.joint_offset)

                # skeleton joint connection
                self.links = self.motion_struct._skeleton.get_links() if self.links is None else self.links

                # skeleton joint names
                self.joint_names = [x._name for x in self.motion_struct._skeleton._joint_lst] if self.joint_names is None else self.joint_names
                self.num_jnt = len(self.joint_names)

                # boundry of mocap clips
                self.valid_range = np.array(self.valid_range)
                
                # calculate norm states given frames
                self.motion_flattened, self.normalization = self.create_norm(self.motion_flattened, 'zscore')
                self.std = self.normalization['std']
                self.avg = self.normalization['avg']
                
                self.frame_dim = self.motion_flattened.shape[-1]

                #reorder and create joint index limits, for retrieval specific element in the feature in the future
                self.motion_flattened, self.std, self.avg = self.transform_data_flattened(self.motion_flattened, self.std, self.avg)

                np.savez(osp.join(self.path,'data.npz'), 
                        motion_flattened = self.motion_flattened, file_lst= self.file_lst, valid_range = self.valid_range, labels = self.labels)
                np.savez(osp.join(self.path,'stats.npz'), 
                            std = self.std, avg = self.avg, frame_dim = self.frame_dim, 
                            joint_offset = self.joint_offset, joint_names= self.joint_names, links = self.links, 
                            data_root_dim = self.data_root_dim,
                            dxdydr_dim_lst = self.dxdydr_dim_lst,
                            joint_dim_lst = self.joint_dim_lst,  
                            vel_dim_lst = self.vel_dim_lst,
                            angle_dim_lst = self.angle_dim_lst,
                            offset_dim_lst = self.offset_dim_lst,
                            height_index = self.height_index,
                            
                            
                        )
            
    
            
            self.test_valid_idx_full = []
            for i_f, (idx_st, idx_ed) in enumerate(self.valid_range):
                self.test_valid_idx_full += range(idx_st, idx_ed - self.test_num_steps)
                idx_ed = idx_ed - self.rollout
                self.valid_range[i_f][1] = idx_ed
                self.valid_idx += list(range(idx_st, idx_ed))
            
            self.valid_idx = np.array(self.valid_idx)
            skip_num = max(len(self.test_valid_idx_full)//self.test_num_init_frame,1)
            self.test_valid_idx = np.array(self.test_valid_idx_full)[::skip_num]
            self.test_ref_clips = np.array([self.motion_flattened[idx:idx+self.test_num_steps] for idx in self.test_valid_idx])

            print('data shape:{}'.format(self.motion_flattened.shape))
        
        self.joint_offset = unit_util.unit_conver_scale(self.unit) *  np.array(self.joint_offset)
        self.joint_parent = bvh_util.get_parent_from_link(self.links)

    def load_new_data(self, path):
        x = self.process_data(path)
        x_normed = self.norm_data(x)
        x_normed = self.transform_new_data(x_normed)
        #print(self.valid_idx, x_normed.shape[0], self.test_num_steps)
        last_index = self.valid_idx[-1] if len(self.valid_idx)>1 else 0
        new_idx = last_index + np.arange(0, x_normed.shape[0]-self.rollout)
        self.valid_idx = np.concatenate([self.valid_idx, new_idx])
        self.motion_flattened = np.asarray(self.motion_flattened).reshape(-1, self.frame_dim)
        self.motion_flattened = np.concatenate([self.motion_flattened,x_normed],axis=0)
        return x_normed
    
    def transform_new_data(self, data):
        num_frame = data.shape[0]
        if self.data_component[0] == 'angle':
            data_piece = [data[...,:self.data_root_dim],data[...,[self.data_root_dim+1]]]
        else:
            data_piece = [data[...,:self.data_root_dim]]
        
        for comp in self.data_component:
            if comp == 'position':
                data_piece.append(data[...,self.data_root_dim:self.data_root_dim+self.num_jnt*3])
                
            if comp == 'velocity':
                data_piece.append(data[...,self.data_root_dim+self.num_jnt*3:self.data_root_dim+self.num_jnt*6])
                
            if comp == 'angle':
                data_denormed = self.denorm_data(data)
                cur_data = data_denormed[...,self.data_root_dim+self.num_jnt*6:self.data_root_dim+self.num_jnt*(6+self.data_rot_dim)]
                cur_data = cur_data.reshape((num_frame, self.num_jnt, -1)).reshape(num_frame * self.num_jnt, -1) 
                cur_data = torch.tensor(cur_data)
                cur_data = self.from_6d_to_rpr(cur_data).numpy().reshape(num_frame, self.num_jnt,-1).reshape(num_frame, -1)
                data_piece.append(cur_data)
                
            if comp == 'offset':
                data_piece.append(data[..., self.data_root_dim+self.num_jnt*(6+self.data_rot_dim):])
        return np.concatenate(data_piece,axis=-1)
    
    def transform_data_flattened(self, data, std, avg):
        num_frame = data.shape[0]
        self.joint_dim_lst = [] #feature dim where local joint locations are stored
        self.vel_dim_lst = [] #feature dim where local joint velocity are stored
        self.angle_dim_lst = [] #feature dim where local joint rotation are stored
        self.offset_dim_lst = [] #feature dim where skeleton offset are stored
        self.data_root_dim  = self.data_root_rot_dim + self.data_root_linear_dim
        #self.dxdy_dim_lst = [0,2] #feature dim of root planar linear velocity
        self.dxdydr_dim_lst = [0, self.data_root_dim] #feature dim of root planar linear velocity & root angular velocity
        
        if self.data_component[0] == 'angle':
            data_piece = [data[...,:self.data_root_dim],data[...,[self.data_root_dim+1]]]
            std_piece = [std[...,:self.data_root_dim],std[...,[self.data_root_dim+1]]]
            avg_piece = [avg[...,:self.data_root_dim],avg[...,[self.data_root_dim+1]]]
            idx = self.data_root_dim+1
            self.height_index = self.data_root_dim
            
        else:
            data_piece = [data[...,:self.data_root_dim]]
            std_piece = [std[...,:self.data_root_dim]]
            avg_piece = [avg[...,:self.data_root_dim]]
            idx = self.data_root_dim 
            self.height_index = self.data_root_dim+1
        
        for comp in self.data_component:
            print(idx, comp, idx+self.num_jnt*3)
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
               
            if comp == 'offset':
                self.offset_dim_lst = [idx, idx+(self.num_jnt)*3]
                data_piece.append(data[...,idx:idx+(self.num_jnt)*3])
                std_piece.append(std[...,idx:idx+(self.num_jnt)*3])
                avg_piece.append(avg[...,idx:idx+(self.num_jnt)*3])
                idx += self.num_jnt*3
        return np.concatenate(data_piece,axis=-1), np.concatenate(std_piece,axis=-1), np.concatenate(avg_piece,axis=-1)
    
    def get_heading_dr(self,data):
        if self.data_root_rot_dim > 1:
            heading_rot = data[:, self.data_root_linear_dim: self.data_root_linear_dim + self.data_root_rot_dim]
            heading_rot = self.from_rpr_to_rotmat(heading_rot)
            global_heading = torch.arctan2(heading_rot[:,1,0], heading_rot[:, 0,0])
        else:
            global_heading = data[:, self.data_root_linear_dim]
        return global_heading

    def get_heading_from_val(self, data):
        if self.data_root_rot_dim > 1:
            heading_rot = geo_util.yaw_to_matrix(data)
            m6d = geo_util.rotation_matrix_to_6d(heading_rot)
            rpr = self.from_6d_to_rpr(m6d)
        else:
            rpr = data
        return torch.tensor(rpr)
    
    def get_height(self,data):
        return data[:, self.height_index]
    
    def get_root_linear_planar_vel(self,data):
        return data[:, :self.data_root_linear_dim]
    
    def get_motion_fpaths(self, path):
        raise NotImplementedError("path_acq: not implemented!")
        
    def process_label(self, path):
        if self.use_cond:
            raise NotImplementedError("read_label_data: not implemented!")

    def process_data(self, fname):
        '''
        take a path as input, output your customized data form
        fname: str
        out: [N, ...]
        '''
        raise NotImplementedError("process_data: not implemented!")
    
    @staticmethod
    def create_norm(mocap_data, norm_mode):
        max = mocap_data.max(axis=0)[0]
        min = mocap_data.min(axis=0)[0]
        avg = mocap_data.mean(axis=0)
        std = mocap_data.std(axis=0)
        std[std == 0] = 1.0
        
        normalization = {
            "mode": norm_mode,
            "max": max,
            "min": min,
            "avg": avg,
            "std": std,
        }

        if norm_mode == "minmax":
            mocap_data = 2 * (mocap_data - min) / (max - min) - 1

        elif norm_mode == "zscore":
            mocap_data = (mocap_data - avg) / std

        else:
            raise ValueError("Unknown normalization mode")
        
        return mocap_data, normalization

    def denorm_data(self,t,device='cpu'):
        
        normalization = self.normalization
        if normalization['mode'] == 'minmax':
            data_max = normalization['max']
            data_min = normalization['min']
            if device !='cpu':
                data_min = torch.tensor(data_min).to(device)
                data_max = torch.tensor(data_max).to(device)
            t = (t + 1) * (data_max - data_min) / 2 + data_min
        
        elif normalization['mode'] == 'zscore':
            data_avg = normalization['avg']
            data_std = normalization['std']
            if device !='cpu':
                data_avg = torch.tensor(data_avg).type(t.dtype).to(device)
                data_std = torch.tensor(data_std).type(t.dtype).to(device)
            
            t = t * data_std + data_avg

        else:
            raise ValueError("Unknown normalization mode")
        return t

    def norm_data(self,t,device='cpu'):
        normalization = self.normalization
        if normalization['mode'] == 'minmax':
            data_max = normalization['max']
            data_min = normalization['min']
            if device !='cpu':
                data_min = torch.tensor(data_min).to(device)
                data_max = torch.tensor(data_max).to(device)
            t = 2 * (t - data_min) / (data_max - data_min) - 1
        
        elif normalization['mode'] == 'zscore':
            data_avg = normalization['avg']
            data_std = normalization['std']
            if device !='cpu':
                data_avg = torch.tensor(data_avg).type(t.dtype).to(device)
                data_std = torch.tensor(data_std).type(t.dtype).to(device)
            t = (t - data_avg) / data_std

        else:
            raise ValueError("Unknown normalization mode")
        return t
    
    def from_6d_to_rpr(self, rotation6d):
        if self.data_rot_rpr == 'aa':
            rotmat =  geo_util.m6d_to_rotmat(rotation6d)
            quat = geo_util.rotmat_to_quat(rotmat)
            return geo_util.quat_to_axis_angle(quat)
        
        elif self.data_rot_rpr == 'expmap':
            rotmat =  geo_util.m6d_to_rotmat(rotation6d)
            quat = geo_util.rotmat_to_quat(rotmat)
            expmap =  geo_util.quat_to_exp_map(quat)
            return expmap

        elif self.data_rot_rpr == 'quat':
            rotmat =  geo_util.m6d_to_rotmat(rotation6d)
            return geo_util.rotmat_to_quat(rotmat)

        elif self.data_rot_rpr == '6d':
            return rotation6d

        else:
            raise NotImplementedError
    
    def from_rpr_to_rotmat(self, rpr):
        if self.data_rot_rpr == 'aa':
            rpr = geo_util.axis_angle_to_quat(rpr)
            return geo_util.quat_to_rotmat(rpr) 
        
        elif self.data_rot_rpr == 'quat':
            return geo_util.quat_to_rotmat(rpr)

        elif self.data_rot_rpr == '6d':
            return geo_util.m6d_to_rotmat(rpr)

        elif self.data_rot_rpr == 'expmap':
            rpr = geo_util.exp_map_to_quat(rpr)
            return geo_util.quat_to_rotmat(rpr)
        else:
            raise NotImplementedError

    def get_dim_by_key(self, category, key):
        if category == "heading":
            rt = [self.data_root_linear_dim,self.data_root_dim]

        elif category == "root_dxdy":
            rt = [0, self.data_root_linear_dim]
        
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
        
        elif category == 'offset':
            #index_offset = self.offset_dim_lst[0]
            rt = self.offset_dim_lst
        return rt
    
    def sync_rpr_within_frame(self, last_frame, frame):
        last_frame = self.denorm_data(last_frame, device=last_frame.device)
        frame = self.denorm_data(frame, device=frame.device)
        
        position = self.angle_frame_pt(frame)#[...,1:,:]
        new_frame = frame.clone()
        if len(self.joint_dim_lst)>0:        
            new_frame[:, self.joint_dim_lst[0]:self.joint_dim_lst[1]] = position.view(frame.shape[0],-1)
        if len(self.vel_dim_lst)>0: 
            new_frame[:, self.vel_dim_lst[0]:self.vel_dim_lst[1]] = position.view(frame.shape[0],-1) - last_frame[:, self.joint_dim_lst[0]:self.joint_dim_lst[1]]
        
        new_frame = self.norm_data(new_frame, device=new_frame.device)
        return new_frame

    def angle_frame_pt(self, frame):
        joint_orientations = torch.zeros((frame.shape[0], self.num_jnt, 3, 3), device=frame.device, dtype=frame.dtype)
        joint_positions = torch.zeros((frame.shape[0], self.num_jnt,3), device=frame.device, dtype=frame.dtype)

        joint_offset_pt = torch.tensor(self.joint_offset, device = frame.device, requires_grad=False, dtype=frame.dtype)
        rotation_rpr = frame[:, self.angle_dim_lst[0]:self.angle_dim_lst[1]].view(-1, self.num_jnt, self.data_rot_dim)
        for i in range(self.num_jnt):
            
            local_rotation = self.from_rpr_to_rotmat(rotation_rpr[..., i, :])
            if self.joint_parent[i] == -1: #root
                joint_orientations[:,i] = local_rotation 
            else:                
                joint_orientations[:,i] = torch.matmul(joint_orientations[:,self.joint_parent[i]].clone(), local_rotation)
                joint_positions[:,i] = joint_positions[:,self.joint_parent[i]] + torch.matmul(joint_orientations[:,self.joint_parent[i]].clone(), joint_offset_pt[i])
        joint_positions[...,1] += frame[..., None, self.height_index]
        return joint_positions


    def vel_frame_pt(self, last_frame, frame):
        vel = frame[...,self.vel_dim_lst[0]:self.vel_dim_lst[1]]
        last_pos = last_frame[...,self.joint_dim_lst[0]:self.joint_dim_lst[1]]
        joint_positions = vel + last_pos
        joint_positions = joint_positions.view(-1,self.num_jnt,3)
        return joint_positions


    def jnts_frame_pt(self, frame):
        joint_positions =  frame[...,self.joint_dim_lst[0]:self.joint_dim_lst[1]]
        joint_positions = joint_positions.view(-1,self.num_jnt,3)
        return joint_positions


    def fk_local_rot_pt(self, rotation_rpr):
        joint_orientations = torch.zeros((self.num_jnt, 3, 3), device=rotation_rpr.device, dtype=rotation_rpr.dtype)
        joint_positions = torch.zeros((self.num_jnt, 3), device=rotation_rpr.device, dtype=rotation_rpr.dtype)

        joint_offset_pt = torch.tensor(self.joint_offset, device = rotation_rpr.device, requires_grad=False, dtype=rotation_rpr.dtype)
        for i in range(self.num_jnt):
            local_rotation = self.from_rpr_to_rotmat(rotation_rpr[..., i,:])
            if self.joint_parent[i] == -1: #root
                joint_orientations[i,:,:] = local_rotation 
            else:                
                joint_orientations[i] = torch.matmul(joint_orientations[self.joint_parent[i]].clone(), local_rotation)
                joint_positions[i] = joint_positions[self.joint_parent[i]] + torch.matmul(joint_orientations[self.joint_parent[i]].clone(), joint_offset_pt[i])
        
        return joint_positions#.view(-1)


    def fk_local_seq(self, frames):
        dtype = frames.dtype
        num_frames = len(frames)
        ang_frames = frames[:,self.angle_dim_lst[0]:self.angle_dim_lst[1]]
        joint_positions = np.zeros((num_frames, self.num_jnt, 3), dtype=dtype)
        joint_orientations = np.zeros((num_frames, self.num_jnt, 3, 3), dtype=dtype)
       
        if self.use_offset:
            joint_offset = frames[0,self.offset_dim_lst[0]:].reshape(-1,3)
        else:
            joint_offset = self.joint_offset
        #joint_offset = joint_offset[None,...].repeat(joint_orientations.shape[0],0)
        
        for i in range(self.num_jnt):
            local_rotation = ang_frames[:, self.data_rot_dim*i: self.data_rot_dim*(i+1)]
            local_rotation = self.from_rpr_to_rotmat(torch.tensor(local_rotation)).numpy()
            if self.joint_parent[i] == -1: #root
                joint_orientations[:,i,:,:] = local_rotation 
            else:                
                joint_orientations[:,i] = np.matmul(joint_orientations[:,self.joint_parent[i]], local_rotation)
                joint_positions[:,i] = joint_positions[:,self.joint_parent[i]] + np.matmul(joint_orientations[:,self.joint_parent[i]], joint_offset[i])
        
        joint_positions[..., 1] += frames[..., [self.height_index]] #height
        return  joint_positions


    def vel_step_seq(self, frames):
        num_frames = len(frames)
        frames = copy.deepcopy(frames)
        new_positions = np.zeros((num_frames, 3*self.num_jnt))
        joint_positions = frames[:, self.joint_dim_lst[0]:self.joint_dim_lst[1]] 
        new_positions[0] = joint_positions[0]
        
        for i in range(1,new_positions.shape[0]):
            new_positions[i, :] = joint_positions[i-1] + frames[i, self.vel_dim_lst[0]:self.vel_dim_lst[1]]     
        
        new_positions = new_positions.reshape((-1, self.num_jnt,3))
        return new_positions

    def jnts_step_seq(self, frames):
        jnts =  copy.deepcopy(frames[...,self.joint_dim_lst[0]:self.joint_dim_lst[1]])
        jnts = jnts.reshape(-1,self.num_jnt,3)
        return jnts

    def x_to_rotation(self, x, mode):
        dxdy = x[...,:self.data_root_linear_dim] 
        if self.data_root_rot_dim>1:
            m6d = self.from_rpr_to_rotmat(x[...,self.data_root_linear_dim:self.data_root_dim])
            dr, _ = geo_util.sepr_rot_heading(m6d)
        else:
            dr = x[...,self.data_root_linear_dim]

        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)
        rot_headings = np.zeros((dxdy.shape[0],3,3))
        rot_headings[0] = np.eye(3)
        for i in range(1, yaws.shape[0]):
            cur_pos = np.zeros((1,3))
            cur_pos[0,0] = dxdy[i,0]
            cur_pos[0,2] = dxdy[i,1]
            dpm_lst[i,:] = copy.deepcopy(dpm)
            dpm += np.dot(cur_pos, geo_util.rot_yaw(yaws[i]))
            rot_headings[i,:] = geo_util.rot_yaw(yaws[i])
           
        #root_rotmat_no_heading = torch.tensor(root_rotmat_no_heading)
        if mode == 'position':
            rotation_0 = x[0, self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            rotation = self.ik_seq(x[0], x[1:])
            rotation_0 = rotation_0.reshape((-1, self.num_jnt, self.data_rot_dim))
            rotation = np.concatenate([rotation_0, rotation], axis = 0)
        
        elif mode == 'angle':
            rotation = x[..., self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            rotation = rotation.reshape((-1, self.num_jnt, self.data_rot_dim))

        elif mode == 'velocity':
            rotation_0 = x[0, self.angle_dim_lst[0]:self.angle_dim_lst[1]]
            jnts = self.vel_step_seq(x)
            x[...,self.joint_dim_lst[0]:self.joint_dim_lst[1]] = jnts.view(x.shape[0],-1)
            rotation = self.ik_seq(x[0],x[1:])
            rotation = np.concatenate([rotation_0, rotation], axis = 0)

        rotation = self.from_rpr_to_rotmat(torch.tensor(rotation)).cpu().numpy()
        rotation[:,0,...] = np.matmul(rot_headings.transpose(0,2,1),rotation[:,0,...])
        rotation = geo_util.rotation_matrix_to_euler(rotation, self.rotate_order)/np.pi*180
        
        dpm_lst[:,1] = x[...,self.height_index]
        return dpm_lst, rotation
    
    def x_to_jnts(self, x, mode):
        dxdy = x[...,:self.data_root_linear_dim] 
        if self.data_root_rot_dim>1:
            m6d = self.from_rpr_to_rotmat(x[...,self.data_root_linear_dim:self.data_root_dim])
            dr, _ = geo_util.sepr_rot_heading(m6d)
        else:
            dr = x[...,self.data_root_linear_dim]
       
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
            x[1:, self.angle_dim_lst[0]:self.angle_dim_lst[1]] = rotations.reshape(-1, self.data_rot_dim*self.num_jnt)
            jnts = self.fk_local_seq(x)
        else:
            x[..., [self.joint_dim_lst[0],self.joint_dim_lst[0]+2]] *= 0
            jnts = self.jnts_step_seq(x)
        
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)
        for i in range(1, jnts.shape[0]):
            cur_pos = np.zeros((1,3))
            cur_pos[0,0] = dxdy[i,0]
            cur_pos[0,2] = dxdy[i,1]
            dpm += np.dot(cur_pos, geo_util.rot_yaw(yaws[i]))
            dpm_lst[i,:] = copy.deepcopy(dpm)
            jnts[i,:,:] = np.dot(jnts[i,:,:], geo_util.rot_yaw(yaws[i])) + copy.deepcopy(dpm)
        return jnts
        
    def x_to_trajs(self,x):
        dxdy = x[...,:self.data_root_linear_dim] 
        if self.data_root_rot_dim>1:
            m6d = self.from_rpr_to_rotmat(x[...,self.data_root_linear_dim:self.data_root_dim])
            dr, _ = geo_util.sepr_rot_heading(m6d)
        else:
            dr = x[...,self.data_root_linear_dim]

        #jnts = np.reshape(x[...,3:69],(-1,self.num_jnt,3))
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)
        for i in range(1, x.shape[0]):
           cur_pos = np.zeros((1,3))
           cur_pos[0,0] = dxdy[i,0]
           cur_pos[0,2] = dxdy[i,1]
           dpm += np.dot(cur_pos,geo_util.rot_yaw(yaws[i]))
           dpm_lst[i,:] = copy.deepcopy(dpm)
        return dpm_lst[...,[0,2]]
    

    def save_bvh(self, out_path, xs):
        xyzs_seq, euler_angle = self.x_to_rotation(xs, 'angle')
        xyzs_seq = xyzs_seq * 1/ unit_util.unit_conver_scale(self.unit)
        joint_offset = self.joint_offset * 1 / unit_util.unit_conver_scale(self.unit)
        bvh_util.output_as_bvh(out_path+'.bvh', xyzs_seq, euler_angle, self.rotate_order,
                            self.joint_names, self.joint_parent, joint_offset, self.fps) 
    

    def __len__(self):
        return len(self.valid_idx)

    def __getitem__(self, idx):
        idx_ = self.valid_idx[idx]
        motion = self.motion_flattened[idx_:idx_+self.rollout]
        return  motion 