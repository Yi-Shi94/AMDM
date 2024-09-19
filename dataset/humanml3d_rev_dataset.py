import torch
import numpy as np
from tqdm import tqdm
import os.path as osp

import dataset.base_dataset as base_dataset
import dataset.util.plot as plot_util

from dataset.util.humanml3d.script.motion_process import recover_from_ric, extract_features
from dataset.util.humanml3d.util.paramUtil import *

class HumanML3D(base_dataset.BaseMotionData):
    NAME = 'HumanML3D_REV'
    def __init__(self, config):
        self.train_split_file = config['data']['train_split']
        self.test_split_file = config['data']['test_split']
        #self.eval_split_file = config['data']['eval_split']
        
        super().__init__(config)

        self.use_eval_split = True
        self.use_cond = False

        self.eval_valid_range = []
        self.test_data = self.load_new_dataset(self.test_split_file)
        
        self.test_valid_idx_full = []
        num = 0
        for i in range(len(self.test_data)):
            length = self.test_data[i].shape[0]
            self.test_valid_idx_full += range(num, num+length-self.test_num_steps)
            num = num+length
        
        self.test_data_flattened = np.concatenate(self.test_data,axis=0)
        self.test_data_flattened = self.norm_data(self.test_data_flattened)
        self.test_data_flattened = self.transform_new_data(self.test_data_flattened)

        skip_num = max(len(self.test_valid_idx_full)//self.test_num_init_frame,1)
        self.test_valid_idx = np.array(self.test_valid_idx_full)[::skip_num]
        self.test_ref_clips = np.array([self.test_data_flattened[idx:idx+self.test_num_steps] for idx in self.test_valid_idx])
       

    def process_data(self, fname):
        # read a single file, convert them into single format
        final_x = np.load(fname)
        if np.any(np.isnan(final_x)):
            return
        # use file num as label
        if self.data_trim_begin:
            final_x = final_x[self.data_trim_begin:]
        if self.data_trim_end:
            final_x = final_x[:self.data_trim_end]
        self.num_file += 1
        return final_x
    
    def get_motion_fpaths(self):
        with open(self.train_split_file) as train_f:
            train_lines = [osp.join(self.path,x.strip()+'.npy') for x in train_f.readlines()]
        return train_lines
    
    def transform_data_flattened(self, data, std, avg):
        return data, std, avg

    def transform_new_data(self, data):
        return data
    
    def load_new_dataset(self, split):
        new_data = []
        with open(split) as f:
            lines = [osp.join(self.path,x.strip()+'.npy') for x in f.readlines()]
        
        for i, line in enumerate(tqdm(lines)):
            data = self.process_data(line)
            #data = self.load_new_data(line)
            #data = self.transform_new_data(data)
            new_data.append(data)

        #new_data_flattened = np.array(new_data_flattened)
        return new_data
    
    def get_height(self, x):
        jnts = self.x_to_jnts(x)
        return jnts[...,0,1]

    def get_heading_dr(self, x):
        return x[..., 0]
    
    def get_root_linear_planar_vel(self, x):
        return x[..., 1:3]


    def plot_jnts(self, x, path=None):
        return plot_util.plot_lafan1(x, links=self.links, save_path=path)
    
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)
    
    def x_to_jnts(self, x, mode=None):
        x = torch.tensor(x)
        jnts = recover_from_ric(x, self.num_jnt, False).detach().numpy()
        return jnts
        
    def x_to_trajs(self,x):
        x = torch.tensor(x)
        jnts = recover_from_ric(x, self.num_jnt, False).detach().numpy()
        return jnts[...,0,[0,2]]