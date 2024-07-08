import policy.envs.base_env as base_env
import policy.envs.target_env as target_env
from render.realtime.mocap_renderer import PBLMocapViewer
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym
import os.path as osp

class JoystickEnv(target_env.TargetEnv):
    NAME = "JOYSTICK"
    def __init__(self, config, model, dataset, device):

        # Need to do this before calling super()
        # otherwise parameter will not be set up
        self.target_direction = 0
        self.target_speed = 0

        super().__init__(config, model, dataset, device)

        condition_size = self.frame_dim * self.num_condition_frames
        # 2 because we are doing cos() and sin()
        self.observation_dim = condition_size + 2
        
        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)

        # tensor buffers for direction and speed
        self.target_direction_buf = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.target_speed_buf = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.joystick_arr = torch.zeros((self.num_parallel, self.max_timestep, 2)) 


    def reset_target(self, indices=None, location=None):
        if not self.is_rendered:
            facing_switch_every = 120
            speed_switch_every = 240
            if self.timestep % facing_switch_every == 0:
                # in training mode, we have tensors
                self.target_direction_buf.uniform_(0, 2 * np.pi)

            if self.timestep % speed_switch_every == 0:
                # in training mode, we have tensors
                choices = torch.linspace(0, 0.8, 9).to(self.device)
                sample = torch.randint(0, choices.size(0), (self.num_parallel, 1))
                self.target_speed_buf.copy_(choices[sample])
            
            self.target[:, 0].add_(10 * self.target_direction_buf.cos().squeeze())
            self.target[:, 1].add_(10 * self.target_speed_buf.sin().squeeze())

        else:
             
            if self.timestep < 120:
                self.target_speed = 4.0
                self.target_direction = np.pi/2

            elif self.timestep < 280:
                self.target_speed = 5.0
                self.target_direction = np.pi*3/4
            
            elif self.timestep < 380:
                self.target_speed = 9.0
                self.target_direction = np.pi/2
            
            elif self.timestep < 600:
                self.target_speed = 5.0
                self.target_direction = np.pi/2
            
            elif self.timestep < 800:
                self.target_speed = 5.0 + (self.timestep-600)/360 * 3
                self.target_direction = np.pi/2 + (self.timestep-600)/180 * np.pi

            elif self.timestep < 900:
                self.target_speed = 3.0
                self.target_direction = np.pi

            self.target.copy_(self.root_xz)
            self.joystick_arr[:,self.timestep,0] = self.target_speed 
            self.joystick_arr[:,self.timestep,1] = self.target_direction 

            if self.timestep % 30 ==0:
                np.save(osp.join(self.int_output_dir,'joystick'), self.joystick_arr)

            self.target[:, 0].add_(10 * np.cos(self.target_direction))
            self.target[:, 1].add_(10 * np.sin(self.target_direction))
            # Overwrite buffer because they are part of the observation returned to controller
            self.target_speed_buf.fill_(self.target_speed)
            # Need to overwrite this for dumping rendering data
            self.target_direction_buf.fill_(self.target_direction)
            self.viewer.update_target_markers(self.target)

        self.calc_potential()

    def calc_progress_reward(self):
        _, target_angle = self.get_target_delta_and_angle()
        direction_reward = target_angle.cos().add(-1)
        speed = self.next_frame[:, [0, 1]].norm(dim=1, keepdim=True)
        speed_reward = (self.target_speed_buf - speed).abs().mul(-1)
        return (direction_reward + speed_reward).exp()
    
    
    
    def reset_initial_frames(self, frame_index=None):
        # Make sure condition_range doesn't blow up
        num_frame_used = len(self.valid_idx)
        num_init = self.num_parallel if frame_index is None else len(frame_index)

        #ensor([[537085]]) ==================
        #tensor([[2122372]]) ==================
        
        start_index = 163639 #torch.randint(0,num_frame_used-1,(num_init,1))#2122372 #torch.randint(0,num_frame_used-1,(num_init,1)) 
        start_index = self.valid_idx[start_index]

        data = torch.tensor(self.dataset.motion_flattened[start_index])
        if self.is_rendered:
            print('starting index:',start_index)
        if frame_index is None:
            self.init_frame = data.clone()
            self.history[:, :self.num_condition_frames] = data.clone()
        else:
            self.init_frame[frame_index] = data.clone()
            self.history[frame_index, :self.num_condition_frames] = data.clone()


    def calc_energy_penalty(self, next_frame):
        return 0

    def calc_action_penalty(self):
        prob_energy = self.action.abs().mean(-1, keepdim=True)
        return 0

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        is_external_step = self.substep == 0

        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip

        self.integrate_root_translation(next_frame)
        
        progress = self.calc_progress_reward()

        if is_external_step:
            self.reward.copy_(progress)
        else:
            self.reward.add_(progress)

        obs_components = list(self.get_observation_components())
        self.done.fill_(self.timestep >= self.max_timestep)
        #print(obs_components[0].shape,obs_components[1].shape)
        obs_components[0] = obs_components[0].squeeze(1)
        
        # Everytime this function is called, should call render
        # otherwise the fps will be wrong
        self.render()

        return (
            torch.cat(obs_components, dim=1),
            self.reward,
            self.done,
            {"reset": self.timestep >= self.max_timestep},
        )

    def integrate_root_translation(self, pose):
        # set new target every step to make sure angle doesn't change
        super().integrate_root_translation(pose)
        self.reset_target()


    def get_target_delta_and_angle(self):
        target_delta = self.target - self.root_xz
        target_angle = (
            torch.atan2(target_delta[:, 1], target_delta[:, 0]).unsqueeze(1)
            + self.root_facing
        )
        return target_delta, -target_angle


    def get_observation_components(self):
        condition = self.get_cond_frame()
       
        _, target_angle = self.get_target_delta_and_angle()
        forward_speed = self.target_speed_buf * target_angle.cos()
        sideway_speed = self.target_speed_buf * target_angle.sin()
        return condition, forward_speed, sideway_speed

    def dump_additional_render_data(self):
        return {
            "extra.csv": {
                "header": "TargetSpeed, TargetFacing",
                "data": torch.cat(
                    (self.target_speed_buf[0], self.target_direction_buf[0]), dim=-1
                ),
            }
        }