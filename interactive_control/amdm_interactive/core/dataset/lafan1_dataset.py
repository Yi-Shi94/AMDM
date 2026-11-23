
import glob
import os.path as osp

import amdm_interactive.core.dataset.base_dataset as base_dataset
import amdm_interactive.core.dataset.util.bvh as bvh_util


class LAFAN1(base_dataset.BaseMotionData):
    NAME = 'LAFAN1'
    def __init__(self, config):
        super().__init__(config)
        self.use_cond = False
        
    def process_data(self, fname):
        # read a single file, convert them into single format
        final_x, motion_struct = bvh_util.read_bvh_loco(fname, self.unit, self.fps, self.root_rot_offset)

        # use file num as label
        if self.data_trim_begin:
            final_x = final_x[self.data_trim_begin:]
        if self.data_trim_end:
            final_x = final_x[:self.data_trim_end]
        self.num_file += 1
        return final_x, motion_struct


    def load_new_data(self, path):
        x = self.process_data(path)[0]
        x_normed = self.norm_data(x)
        return x_normed

    def get_motion_fpaths(self):
        return sorted(glob.glob(osp.join(self.path, '*.{}'.format('bvh'))))  # deterministic clip order
