import glob
import numpy as np

import dataset.base_dataset as base_dataset
import dataset.util.amass as amass_util
import dataset.util.plot as plot_util
import os.path as osp

class AMASS(base_dataset.BaseMotionData):
    NAME = 'AMASS'
    def __init__(self, config):
        super().__init__(config)
        
    def plot_jnts(self, x, path=None):
        return plot_util.plot_jnt_vel(x, self.links, plot_util.plot_lafan1, self.fps, path)
        
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)
    
    def get_motion_fpaths(self):
        path =  osp.join(self.path,'**/*.{}'.format('npz'))
        file_lst = glob.glob(path, recursive = True)
        return file_lst
    
    def process_data(self, fname):
        motion_struct = amass_util.init_motion_from_amass(fname)
        offset_feature = motion_struct._skeleton.get_joint_offset()
        offset_feature = np.array(offset_feature).reshape(1,-1)
        
        xs = amass_util.load_amass_file(fname)
        offset_feature = offset_feature.repeat(xs.shape[0],0)
        xs = np.concatenate([xs, offset_feature],axis=-1)
        return xs, motion_struct   
    
    def __len__(self):
        return len(self.valid_idx)

    def __getitem__(self, idx):
        idx_ = self.valid_idx[idx]
        motion = self.motion_flattened[idx_:idx_+self.rollout]
        return  motion


if __name__=='__main__':
    pass
