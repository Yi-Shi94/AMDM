
import policy.envs.base_env as base_env
from render.realtime.mocap_renderer import PBLMocapViewer
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym
from multiprocessing import Process

class RandomPlayEnv(base_env.EnvBase):
    NAME = "RandomPlay"
    def __init__(self, config, model, dataset, device):      
        #super().__init__(config, model, dataset, device)
        self.device = device
        self.config = config
        self.model = model
        self.dataset = dataset

        self.interative_text = False
        self.cur_extra_info = None
        self.updated_text = False

        self.links = self.dataset.links
        self.valid_idx = self.dataset.valid_idx

        self.frame_dim = self.dataset.frame_dim
        self.action_dim = self.dataset.frame_dim
        self.valid_range = self.dataset.valid_range
        self.sk_dict = dataset.skel_info
        self.data_fps = self.dataset.fps

        self.is_rendered = True
        self.num_parallel = config.get('num_parallel',1)
        self.num_parallel_test = config.get('num_parallel_test',1)

        self.frame_skip = config.get('frame_skip',1)
        self.max_timestep = config.get('max_timestep_test',10000)
        self.camera_tracking = config.get('camera_tracking',True)
        self.int_output_dir = config['int_output_dir']

        self.num_condition_frames = 1

        self.timestep = 0
        self.substep = 0
        self.record_timestep = 0
        self.base_action = torch.zeros((self.num_parallel, 1, self.action_dim)).to(
            self.device
        )

        if 'file_name' in config:
            file_idx = dataset.get_motion_fpaths().index(config['file_name'])
        else:
            file_idx = torch.randint(0, len(self.valid_range)-1, (self.num_parallel, 1))
        
        timestep_range =  torch.tensor(self.valid_range[file_idx]).squeeze().to(self.device) 
        
        self.timestep_start = timestep_range[...,0]
        self.timestep_end = timestep_range[...,1]

        self.clip_timestep =self.timestep_start

        if 'st_frame_idx' in config and 'file_name' in config:
            self.init_frame_idx = min(self.timestep_start + config['st_frame_idx'], self.timestep_end)
        elif  'st_frame_idx' in config:
            self.init_frame_idx = config['st_frame_idx']
        else:
            self.init_frame_idx = torch.randint(self.timestep_start, self.timestep_end-1, (self.num_parallel, 1))


        #self.init_frame_idx = config.get('st_frame_index',5000)
        self.reward = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.root_facing = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.root_xz = torch.zeros((self.num_parallel, 2)).to(self.device)
        self.root_y = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.done = torch.zeros((self.num_parallel, 1)).bool().to(self.device)

        self.history_size = 1
        self.history = torch.zeros(
            (self.num_parallel, self.history_size, self.frame_dim)
        ).to(self.device)

        self.parallel_ind_buf = (
            torch.arange(0, self.num_parallel).long().to(self.device)
        )

        high = np.inf * np.ones([self.action_dim])
        self.action_space = gym.spaces.Box(-high, high, dtype=np.float32)
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)

        self.viewer = PBLMocapViewer(
            self,
            num_characters=self.num_parallel,
            target_fps=self.data_fps,
            camera_tracking=self.camera_tracking,
        )

        if self.is_rendered:
            self.record_num_frames = np.zeros((self.num_parallel_test,))
            self.record_motion_seq = np.zeros((self.num_parallel_test, self.max_timestep, self.dataset.frame_dim))
            self.record_timestep = 0

    def integrate_root_translation(self, pose):
        pose_denorm = self.dataset.denorm_data(pose, device=pose.device)
        mat = self.get_rotation_matrix(self.root_facing)
        displacement = (mat * pose_denorm[..., :2].unsqueeze(1)).sum(dim=2)
        dr = self.dataset.get_heading_dr(pose_denorm)

        self.root_facing.add_(dr).remainder_(2 * np.pi)
        self.root_xz.add_(displacement)
        
        self.history = self.history.roll(1, dims=1)
        self.history[:, 0] = pose


    def get_cond_frame(self):
        condition = self.history[:, : self.num_condition_frames]
        b = condition.shape[0]
        condition = condition.view(b,-1)
        return condition
    
    def reset_initial_frames(self, frame_index=None):
        # Make sure condition_range doesn't blow up
        #ensor([[537085]]) ==================
        #tensor([[2122372]]) ==================
        data = torch.tensor(self.dataset.motion_flattened[self.init_frame_idx])
        data = data[None,...].to(self.device).float()

        #data = self.dataset.denorm_data(data.cpu()).to(self.device)
        
        if frame_index is None:
            self.init_frame = data.clone()
            self.history[:, :self.num_condition_frames] = data.clone()
        else:
            self.init_frame[frame_index] = data.clone()
            self.history[frame_index, :self.num_condition_frames] = data.clone()

    def get_next_frame(self, action=None):
        condition = self.get_cond_frame()
       
        
        with torch.no_grad():
            output = self.model.eval_step(condition, self.cur_extra_info)
            #output = self.dataset.unify_rpr_within_frame(condition, output)
        
        return output
        

    def reset(self, indices=None):
        self.timestep = 0
        self.substep = 0
        self.root_facing.fill_(0)
        self.root_xz.fill_(0)
        self.done.fill_(False)

        # Need to clear this if we want to use calc_foot_slide()
        #self.foot_pos_history.fill_(1)
        #self.reset_initial_frames()
        #obs_components = self.get_observation_components()

        #return torch.cat(obs_components, dim=-1)
    

    def calc_env_state(self, next_frame):
        #self.next_frame = next_frame
        is_external_step = self.substep == 0

        self.reward.fill_(1) 
        
        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip

        self.integrate_root_translation(next_frame)
 
        #foot_slide = self.calc_foot_slide()
        #self.reward.add_(foot_slide.sum(dim=-1, keepdim=True) * -10.0)

        self.done.fill_(self.timestep >= self.max_timestep)

        self.render()
        return (
            None,#torch.cat(obs_components, dim=1),
            self.reward,
            self.done,
            {"reset": self.timestep >= self.max_timestep},
        )
    
    def render(self, mode="human"):
        frame = self.dataset.denorm_data(self.history[:, 0], device=self.device).cpu().numpy()
        self.viewer.render(
            torch.tensor(self.dataset.x_to_jnts(frame, mode='angle'),device=self.device, dtype=self.history.dtype),  # 0 is the newest
            self.root_facing,
            self.root_xz,
            0.0,  # No time in this env
            0.0   #self.action,
        )

    def dump_additional_render_data(self):
        pass
