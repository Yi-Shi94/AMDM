import copy
import glob
import torch
import torch.optim as optim
import torch.utils.data as data

import tqdm
import numpy as np
import os

from dataset.util.humanml3d.util.fixseed import fixseed
import dataset.base_dataset as base_dataset
import dataset.util.amass as amass_util
import dataset.util.plot as plot_util
import dataset.util.geo as geo_util
import dataset.util.unit as unit_util
import dataset.util.skeleton_info as skeleton_info
import os.path as osp
import codecs as cs
from dataset.util.humanml3d.util.plot_script import plot_3d_motion
from dataset.util.humanml3d.util.metrics import calculate_skating_ratio
from dataset.util.humanml3d.script.motion_process import recover_from_ric 

def sample_to_motion(sample):
    n_joints = 22
    # (bs, 263, 1, 120)
    # In case of random projection, this already includes undoing the random projection
    sample = sample.squeeze()
    sample = recover_from_ric(sample, n_joints)
    sample = sample.permute(0, 2, 3, 1)
    return sample


class eval_HumanML3D_AMDM(data.Dataset):
    NAME= 'eval_HumanML3D_AMDM'
    def __init__(self, model, eval_dataset, dataloader, mm_num_samples, mm_num_repeats, max_motion_length, num_samples_limit, save_dir=None, seed=None):
        assert seed is not None, "seed must be provided"
        self.dataloader = dataloader
        self.dataset = dataloader.dataset
        self.eval_dataset = eval_dataset
        self.save_dir = save_dir
        assert save_dir is not None
        assert mm_num_samples < len(dataloader.dataset)

        # create the target directory
        os.makedirs(self.save_dir, exist_ok=True)
        self.max_motion_length = max_motion_length
        self.model = model
        self.device = model.device
        real_num_batches = len(dataloader)
        if num_samples_limit is not None:
            real_num_batches = num_samples_limit // dataloader.batch_size + 1
        print('real_num_batches', real_num_batches)

        generated_motion = []
        # NOTE: mm = multi-modal

        model.eval()

        with torch.no_grad():
            for i, (motion, model_kwargs) in enumerate(tqdm.tqdm(dataloader)):

                if num_samples_limit is not None and len(generated_motion) >= num_samples_limit:
                    break

                repeat_times =  1
    
                for t in range(repeat_times):        
                    # setting seed here make sure that the same seed is used even continuing from unfinished runs
                    

                    batch_file = f'{i:04d}_{t:02d}.pt'
                    batch_path = os.path.join(self.save_dir, batch_file)

                    # reusing the batch if it exists
                    if os.path.exists(batch_path):
                        # [bs, njoints, nfeat, seqlen]
                        sample = torch.load(batch_path, map_location=motion.device)
                        print(f'batch {batch_file} exists, loading from file')
                    else:
                        # [bs, njoints, nfeat, seqlen]
                        batch = motion.shape[0]
                        lengths =  model_kwargs['y']['lengths']
                        
                        frame_index = (torch.rand(batch) * lengths).long()
                        start_x = motion[torch.arange(batch), :, 0, frame_index] #torch.index_select(motion[:, :, 0], -1, frame_index).to(self.device)
                        
                        start_x = self.dataset.t2m_dataset.inv_transform(start_x)
                        start_x = self.eval_dataset.norm_data(start_x).to(self.device)
                        
                        sample = self.model.eval_seq(
                            start_x,
                            None,
                            self.max_motion_length,
                            1)
                        sample = self.eval_dataset.denorm_data(sample, device=self.device)
                        #valid_mask = torch.prod(torch.prod(torch.isnan(sample.squeeze()),dim=-1),dim=-1)==0
                        #invalid_mask = ~ valid_mask
                        #print('non-nan:{}/{}'.format(torch.sum(valid_mask),valid_mask.shape[0]))
                        #if invalid_mask.sum()>0:
                        #    jnts = self.eval_dataset.x_to_jnts(sample[invalid_mask][0].squeeze().cpu().numpy())
                        #    self.eval_dataset.plot_jnts(jnts)

                        #jnts = self.eval_dataset.x_to_jnts(sample[0].squeeze().cpu().numpy())
                        #self.eval_dataset.plot_jnts(jnts)
                        
                        #motion = self.dataset.t2m_dataset.inv_transform(motion[0, :, 0, :].permute(1,0))
                        #jnts = self.eval_dataset.x_to_jnts(motion.squeeze().cpu().numpy())
                        #self.eval_dataset.plot_jnts(jnts)

                        #sample = sample[valid_mask]
                        #sample = sample[:dataloader.batch_size]
                        sample = sample[:,:,None,:]
                        # save to file
                        #torch.save(sample, batch_path)
                    
                    #jnts = self.eval_dataset.x_to_jnts(sample.squeeze()[0])
                    #self.eval_dataset.plot_jnts(jnts)
                    
                    cur_motion = sample_to_motion(sample)
                    skate_ratio, skate_vel = calculate_skating_ratio(cur_motion)
            
                    # Compute error for key xz locations
                    if t == 0:
                        sub_dicts = [{'motion': sample[bs_i].squeeze().cpu().numpy(),
                                    'length': model_kwargs['y']['lengths'][bs_i].cpu().numpy(),
                                    'skate_ratio': skate_ratio[bs_i],
                                    } for bs_i in range(sample.shape[0])]
                        generated_motion += sub_dicts



        self.generated_motion = generated_motion
        

    def __len__(self):
        return len(self.generated_motion)


    def __getitem__(self, item):
        data = self.generated_motion[item]
        motion, m_length = data['motion'], data['length']

        if 'skate_ratio' in data.keys():
            skate_ratio = data['skate_ratio']
        else:
            skate_ratio = -1

        if self.dataset.mode == 'eval':
            
            denormed_motion = motion
            #denormed_motion = self.dataset.t2m_dataset.inv_transform(normed_motion)
            renormed_motion = (denormed_motion - self.dataset.mean_for_eval[None,...]) / self.dataset.std_for_eval[None,...] # according to T2M norms
            motion = renormed_motion
            # This step is needed because T2M evaluators expect their norm convention
    
        return motion, m_length, skate_ratio

