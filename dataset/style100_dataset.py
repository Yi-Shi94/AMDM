import copy
import glob
import os
import csv
import numpy as np
import dataset.base_dataset as base_dataset
import dataset.util.bvh as bvh_util
import dataset.util.unit as unit_util
import dataset.util.geo as geo_util
import dataset.util.plot as plot_util
import os.path as osp

class STYLE100(base_dataset.BaseMotionData):
    NAME = 'STYLE100'
    def __init__(self, config):
        self.only_forward = False
        if 'info_path' in config['data']:
            info_path = config['data']['info_path']
            self.info_dict = self.get_data_info(info_path)
            self.only_forward = config['data'].get('only_forward', False)
        super().__init__(config)
        self.use_cond = False

    def get_data_info(self, info_path):
        info_list = []
        with open(info_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                info_list.append(row)
        info_dict = dict()
        for info in info_list:
            name = info['STYLE_NAME']
            br_start, br_end = int(info['BR_START']), int(info['BR_STOP'])
            bw_start, bw_end = int(info['BW_START']), int(info['BW_STOP'])
            fr_start, fr_end = int(info['FR_START']), int(info['FR_STOP'])
            fw_start, fw_end = int(info['FW_START']), int(info['FW_STOP'])
            id_start, id_end = int(info['ID_START']), int(info['ID_STOP'])
            sr_start, sr_end = int(info['SR_START']), int(info['SR_STOP'])
            sw_start, sw_end = int(info['SW_START']), int(info['SW_STOP'])
            tr1_start, tr1_end = info['TR1_START'], info['TR1_STOP']
            tr2_start, tr2_end = info['TR2_START'], info['TR2_STOP']
            tr3_start, tr3_end = info['TR3_START'], info['TR3_STOP']

            time_dict = {}
            time_dict['BR'] = (br_start, br_end)
            time_dict['BW'] = (bw_start, bw_end)
            time_dict['FR'] = (fr_start, fr_end)
            time_dict['FW'] = (fw_start, fw_end)
            time_dict['ID'] = (id_start, id_end)
            time_dict['SR'] = (sr_start, sr_end)
            time_dict['SW'] = (sw_start, sw_end)
            time_dict['TR1'] = (tr1_start, tr1_end)
            time_dict['TR2'] = (tr2_start, tr2_end)
            time_dict['TR3'] = (tr3_start, tr3_end)

            info_dict[name] = time_dict
        return info_dict
        
    def get_motion_fpaths(self):
        path =  osp.join(self.path,'**/*.{}'.format('bvh'))
        file_lst = glob.glob(path, recursive = True)
        if self.only_forward:
            file_lst = [f for f in file_lst if 'FR' in f or 'FW' in f.split('/')[-1]]
        return file_lst

    def process_data(self, fname):
        #labal_text = fname.split('/')[-2]
        #read a single file, convert them into single format
        #out = bvh_util.load_bvh_info(fname)
        style_name, style_action = fname.split('/')[-1].split('.')[0].split('_')
        if hasattr(self, 'info_dict'):
            frame_start, frame_end = self.info_dict[style_name][style_action]
        else: 
            frame_start, frame_end = self.data_trim_begin, self.data_trim_end
        
        final_x, motion_struct = bvh_util.read_bvh_loco(fname, self.unit, self.fps, self.root_rot_offset)
        return final_x, motion_struct

    def __len__(self):
        return len(self.valid_idx)

    def __getitem__(self, idx):
        idx_ = self.valid_idx[idx]
        motion = self.motion_flattened[idx_:idx_+self.rollout]
        return motion
    
    def plot_jnts(self, x, path=None):
        return plot_util.plot_multiple(x, self.links, plot_util.plot_lafan1, self.fps, path)
    
    def plot_traj(self, x, path=None):
        return plot_util.plot_traj_lafan1(x, path)






