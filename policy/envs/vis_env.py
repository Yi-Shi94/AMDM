import os
import torch
import math
import policy.envs.base_env as base_env
from render.realtime.mocap_renderer import PBLMocapViewer
import gymnasium as gym
import numpy as np

class DataVisEnv(gym.Env):
    NAME = "DataVisEnv"
    def __init__(self, config, model, dataset, device):  
        #self.file_name = config['file_name']
        self.start_timestep = config['start_timestep']
        self.max_timestep = config['max_timestep']
        self.num_parallel = config["num_parallel"]
        self.camera_tracking = config.get('camera_tracking',True)
        self.device = device
        self.is_rendered = True

        self.frame_skip = 1
        self.num_condition_frames = 1
        self.dataset = dataset
        self.frame_dim = dataset.frame_dim
        self.data_fps = dataset.fps
        self.sk_dict = dataset.skel_info
       
        self.links = self.dataset.links
        self.valid_idx = self.dataset.valid_idx
        self.valid_range = self.dataset.valid_range

        self.use_cond = dataset.use_cond
        
        self.timestep = torch.zeros((self.num_parallel, 1)).to(self.device)
        
        file_idx = torch.randint(0, len(self.valid_range)-1, (self.num_parallel, 1))
        timestep_range =  torch.tensor(self.valid_range[file_idx]).squeeze().to(self.device) 
        
        self.timestep_start = timestep_range[...,0]
        self.timestep_end = timestep_range[...,1]
        self.clip_timestep =self.timestep_start
        
    
        self.root_facing = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.root_xz = torch.zeros((self.num_parallel, 2)).to(self.device)
        self.root_y = torch.zeros((self.num_parallel, 1)).to(self.device)

        self.reward = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.done = torch.zeros((self.num_parallel, 1)).bool().to(self.device)

        self.history_size = 5
        self.history = torch.zeros(
            (self.num_parallel, self.history_size, self.frame_dim)
        ).to(self.device)

        self.parallel_ind_buf = (
            torch.arange(0, self.num_parallel).long().to(self.device)
        )

        self.action_space = gym.spaces.Box(-1, 1)
        self.observation_space = gym.spaces.Box(-1, 1)
        self.viewer = PBLMocapViewer(
            self,
            num_characters=self.num_parallel,
            target_fps=self.data_fps,
            camera_tracking=self.camera_tracking,
        )

    def get_valid_range(self, valid_index):
        st = 0
        ed = 0
        skip_flag = False 
        st_ed_lst = []
        for i in range(valid_index[-1]):
            if i not in valid_index and not skip_flag:
                ed = i
                st_ed_lst.append([st, ed])
                skip_flag = True

            elif i in valid_index and skip_flag:
                st = i
                skip_flag = False
        
        return st_ed_lst

    def get_rotation_matrix(self, yaw, dim=2):
        zeros = torch.zeros_like(yaw)
        ones = torch.ones_like(yaw)
        if dim == 3:
            col1 = torch.cat((yaw.cos(), yaw.sin(), zeros), dim=-1)
            col2 = torch.cat((-yaw.sin(), yaw.cos(), zeros), dim=-1)
            col3 = torch.cat((zeros, zeros, ones), dim=-1)
            matrix = torch.stack((col1, col2, col3), dim=-1)
        else:
            col1 = torch.cat((yaw.cos(), yaw.sin()), dim=-1)
            col2 = torch.cat((-yaw.sin(), yaw.cos()), dim=-1)
            matrix = torch.stack((col1, col2), dim=-1)
        return matrix

    def get_next_frame(self):
        #cur_time_step
       
        data = self.dataset.motion_flattened[self.clip_timestep]
        data = self.dataset.denorm_data(data)
        data = torch.tensor(data).to(self.device)
            
        self.timestep += 1
        self.clip_timestep += 1
        return data

    def reset_initial_frames(self, indices=None):
        
        file_idx = torch.randint(0, len(self.valid_range)-1, (self.num_parallel, 1))
        timestep_range = torch.tensor(self.valid_range[file_idx]).squeeze().to(self.device) 
        timestep_start = timestep_range[...,0]
        clip_timestep = torch.tensor(self.timestep_start)
        timestep_end = timestep_range[...,1]

        if indices is not None:
            self.clip_timestep[indices] = clip_timestep[indices]
        else:
            self.timestep_start = timestep_start
            self.clip_timestep = clip_timestep
            self.timestep_end = timestep_end

    def seed(self, seed):
        return 

    def reset_index(self, indices=None):
        self.root_facing.fill_(0)
        self.root_xz.fill_(0)
        self.done.fill_(False)
        self.reset_initial_frames(indices)    

    def integrate_root_translation(self, pose):
        mat = self.get_rotation_matrix(self.root_facing)
        displacement = (mat * pose[..., :2].unsqueeze(1)).sum(dim=2)
        dr = self.dataset.get_heading_dr(pose)[...,None]
        #print('dd',dr.shape)
        self.root_facing.add_(dr).remainder_(2 * np.pi)
        self.root_xz.add_(displacement)
        
        self.history = self.history.roll(1, dims=1)
        self.history[:, 0].copy_(pose)

    def calc_env_state(self, next_frame):
        if next_frame is None:
            return (
                None,
                self.reward,
                self.done,
                {"reset": True},
            )

        self.integrate_root_translation(next_frame)

        #foot_slide = self.calc_foot_slide()
        #self.reward.add_(foot_slide.sum(dim=-1, keepdim=True) * -10.0)
        #obs_components = self.get_observation_components()

        done = self.clip_timestep>=self.timestep_end
        
        #print(done.shape, self.clip_timestep.shape, self.timestep_end.shape, (self.clip_timestep>=self.timestep_end).shape)
        self.done = done
        self.render()

        return (
            None,
            self.reward,
            self.done,
            {"reset": done},
        )


    
    def render(self, mode="human"):
        
        self.viewer.render(
            torch.tensor(self.dataset.x_to_jnts(self.history[:, 0].cpu().numpy(), mode='angle'),device=self.device),  # 0 is the newest
            self.root_facing,
            self.root_xz,
            0.0,  # No time in this env
            0.0   #self.action,
        )

    def dump_additional_render_data(self):
        pass
