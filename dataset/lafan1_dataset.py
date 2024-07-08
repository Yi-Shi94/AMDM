
import glob
import os.path as osp

import dataset.base_dataset as base_dataset
import dataset.util.bvh as bvh_util
import dataset.util.plot as plot_util


class LAFAN1(base_dataset.BaseMotionData):
    NAME = 'LAFAN1'
    def __init__(self, config):
        super().__init__(config)
        self.use_cond = False
        
    def process_data(self, fname):
        # read a single file, convert them into single format
        final_x, motion_struct = bvh_util.read_bvh_loco(fname, self.unit, self.fps)

        # use file num as label
        if self.data_trim_begin:
            final_x = final_x[self.data_trim_begin:]
        if self.data_trim_end:
            final_x = final_x[:self.data_trim_end]
        self.num_file += 1
        return final_x, motion_struct


    def get_motion_fpaths(self):
        return glob.glob(osp.join(self.path, '*.{}'.format('bvh')))
    
    def plot_jnts_single(self, x):
        return plot_util.plot_lafan1(x,links=self.links)

    def plot_jnts(self, x, path=None):
        return plot_util.plot_multiple(x, self.links, plot_util.plot_lafan1, self.fps, path)
        
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)
