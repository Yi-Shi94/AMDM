import policy.envs.base_env as base_env
from render.realtime.mocap_renderer import PBLMocapViewer
import dataset.util.geo as geo_util 

import os.path as osp
import copy
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym
import policy.envs.target_env as target_env
from random import random

class PathEnv(target_env.TargetEnv):
    def __init__(self, config, model, dataset, device):
        super().__init__(
            config, model, dataset, device
        )

        # controller receives 4 upcoming targets
        self.lookahead = 4
        # time gap between each lookahead frame
        # 15 frames is 0.5 seconds in real-time
        self.lookahead_skip = 4
        self.lookahead_gap = 15
        condition_size = self.frame_dim * self.num_condition_frames
        self.observation_dim = condition_size + 2 * self.lookahead

        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)

        # Define path equal to episode length
        # Should be careful about the magnitude of the path
        
        #speed = 0.4
        #scale = 800
        
        #t = torch.arange(-20,20,1).to(device)/200.0 
        #y = speed*scale*t*1.0
        #x = -y
        
        #x[20:] *= -1  
        #print(x,y)

        #x = -y     
        #t = torch.linspace(0, 2 * np.pi, self.max_timestep).to(device)
        
        # Heart
        #scale = 0.5
        #x = t.sin().pow(3).mul(16 * scale)
        #y = (
        #     (1 * t).cos().mul(13 * scale)
        #     - (2 * t).cos().mul(5 * scale)
        #     - (3 * t).cos().mul(2 * scale)
        ##     - (4 * t).cos().mul(1 * scale)
        #)
        # # Test Easy
        #y = (
        #    (1 * t).cos().mul(4 * scale)
        #     - (2 * t).cos().mul(3 * scale)
        #     - (3 * t).cos().mul(12 * scale)
        #     - (4 * t).cos().mul(1 * scale)
        #)
        # # Test Hard
        # y = (
        #     (1 * t).cos().mul(4 * scale)
        #     - (2 * t).cos().mul(4 * scale)
        #     - (3 * t).cos().mul(4 * scale)
        #     - (4 * t).cos().mul(16 * scale)
        # )

        #t = torch.linspace(-20,20,1).to(device)
        #scale = 5
        #speed = 2
        #y = speed*scale*t
        #x = -y        
        
        # Figure 8
        #scale = 38
        #speed = 0.42
        #x = scale * (speed * t).sin()
        #y = scale * (speed * t).sin() * (speed * t).cos()
        
        # Double Figure 8
        # scale = 50
        # speed = 2
        # x = scale * t.pow(1 / 4) * (speed * t).sin()
        # y = scale * t.pow(1 / 4) * (speed * t).sin() * (speed * t).cos()

        # Figure 8 Tear Drop
        # scale = 50
        # speed = 2
        # x = scale * (speed * t).sin().pow(2)
        # y = scale * (speed * t).sin().pow(2) * (speed * t).cos()

        # Figure 8 with Stop
        # scale = 60
        # speed = 2
        # x = scale * (speed * t).sin().pow(3)
        # y = scale * (speed * t).sin().pow(3) * (speed * t).cos()

        #self.path = torch.stack((x, y), dim=1)
        self.path = self.sample_random_traj_nodr(1)[0]
        """ self.path = torch.zeros(self.max_timestep//4,2).to(self.device).float()
        radius = 2
        theta = np.linspace(0, 2*np.pi, self.max_timestep//4)
        x = radius * np.cos(theta) - radius 
        y = radius * np.sin(theta)
        self.path[...,0] = torch.from_numpy(x).to(self.device)
        self.path[...,1] = torch.from_numpy(y).to(self.device) """
        #torch.tensor(np.load(osp.join(self.int_output_dir,'traj.npy'))).to(self.device)
     
        #self.target = torch.ones(())
        #self.path = self.genetrate_random_path()[0]
        
        if self.is_rendered:
            np.save(osp.join(self.int_output_dir,'traj.npy'), self.path.cpu().detach().numpy())
            print(osp.join(self.int_output_dir,'traj.npy'))
            self.viewer.add_path_markers(self.path)

    def sample_random_traj(self, num_parallel=1):
        
        ar = torch.normal(mean=torch.zeros(num_parallel,self.max_timestep,1), std=torch.ones(num_parallel,self.max_timestep,1)*0.0002) #0.0002
        axy = torch.normal(mean=torch.zeros(num_parallel,self.max_timestep,2), std=torch.ones(num_parallel,self.max_timestep,2)*0.0013) #0.0013 #0.0024
        dr = torch.cumsum(ar, axis = 1).numpy()
        dxy = torch.cumsum(axy, axis = 1).numpy()

        traj = np.zeros((num_parallel,self.max_timestep,3))
        dpm = np.zeros((num_parallel, 3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)
        for i in range(1, self.max_timestep):
           cur_pos = np.zeros((num_parallel, 3))
           cur_pos[:,0] = dxy[:,i,0]
           cur_pos[:,2] = dxy[:,i,1]
           
           dpm += np.matmul(cur_pos,geo_util.rot_yaw(yaws[i]))
           traj[:,i,:] = copy.deepcopy(dpm)
        return torch.tensor(traj[...,[0,2]]).to(self.device).float()
    

    def sample_random_traj_nodr(self, num_parallel=1):
        traj = torch.zeros(num_parallel,self.max_timestep,2)
        vel = torch.zeros(num_parallel,2)
        pos = torch.zeros(num_parallel,2)
        for i in range(self.max_timestep):
            acc = torch.normal(mean=torch.zeros(num_parallel,2), std=torch.ones(num_parallel,2)*0.0025)
            vel += acc
            pos += vel
            traj[:,i] = pos.clone()
        traj = traj.to(self.device)
        return traj


    def generate_random_traj(self, num_parallel=1):
        start_x_index = torch.randint(self.dataset.motion_flattened.shape[0],(1,))
        
        start_x = self.dataset.motion_flattened[start_x_index]
        start_x = torch.tensor(start_x, device = self.device).float()
        self.fixed_init_frame = start_x
        seqs =  self.model.eval_seq(start_x, None, self.max_timestep, num_parallel).cpu().detach().numpy()
        seqs = self.dataset.denorm_data(seqs)
        trajs = []
        for i in range(seqs.shape[0]):
            trajs.append(self.dataset.x_to_trajs(seqs[i]))
        trajs = torch.tensor(trajs).to(self.device).float()
        return trajs

    def reset(self, indices=None):
        if self.is_rendered:
            self.path_offsets = torch.zeros(self.num_parallel, 1).long()
        else:
            self.path_offsets = torch.randint(
                0, self.path.size(0), (self.num_parallel, 1)
            ).long()

        if not self.is_rendered:
            self.path = self.generate_random_traj()[0]

        if indices is None:
            self.root_facing.fill_(0)
            self.root_xz.fill_(0)
            self.reward.fill_(0)
            self.timestep = 0
            self.substep = 0
            self.done.fill_(False)
            # value bigger than contact_threshold
            #self.foot_pos_history.fill_(1)

            self.reset_target()
            self.reset_initial_frames()
        else:
            self.root_facing.index_fill_(dim=0, index=indices, value=0)
            self.root_xz.index_fill_(dim=0, index=indices, value=0)
            self.reward.index_fill_(dim=0, index=indices, value=0)
            self.done.index_fill_(dim=0, index=indices, value=False)
           
            self.reset_target(indices)
            self.reset_initial_frames(indices)
            # value bigger than contact_threshold
            #self.foot_pos_history.index_fill_(dim=0, index=indices, value=1)

        obs_components = self.get_observation_components()
        return torch.cat(obs_components, dim=1)
    
    def reset_initial_frames(self, frame_index=None):
        super().reset_initial_frames(frame_index)

        # set initial root position to random place on path
        #self.root_xz.copy_(self.path[self.path_offsets.squeeze(1)])
        self.root_xz.copy_(self.path[0])
        next_two = (
            torch.arange(0, 2) * self.lookahead_gap
            + self.path_offsets
            + self.lookahead_skip
        ) % self.path.size(0)
        delta = self.path[next_two[:, 1]] - self.path[next_two[:, 0]]
        facing = 0 #-torch.atan2(delta[:, 1], delta[:, 0]).unsqueeze(1)
        self.root_facing.copy_(facing)
        
        if self.is_rendered:
            #print(facing)
            #cos = torch.cos(facing)
            #sin = torch.sin(facing)
            #rot_mat = torch.tensor([[cos, -sin],[sin, cos]])[None,...].to(self.device)  
            
            #torch.matmul(rot_mat, self.path[...,None])[...,0]
            #print(rot_mat)
            #print(rotated_path)
            #print(osp.join(self.int_output_dir,'traj.npy'), rotated_path.shape)
            
            # don't forget to convert feet to meters
            centre = self.path.mean(dim=0) * 0.3048
            xyz = torch.nn.functional.pad(centre, pad=[0, 1]).cpu().numpy()
            self.viewer.camera.lookat(xyz)

    def reset_target(self, indices=None, location=None):
        # don't add skip to accurate calculate is target is close
        index = (
            self.timestep + self.path_offsets.squeeze(1) + self.lookahead_skip
        ) % self.path.size(0)
        self.target.copy_(self.path[index])
        
        self.calc_potential()

        if self.is_rendered:
            self.viewer.update_target_markers(self.target)

    def get_delta_to_k_targets(self):
        # + lookahead_skip so it's not too close to character
        next_k = (
            torch.arange(0, self.lookahead) * self.lookahead_gap
            + self.timestep
            + self.path_offsets
            + self.lookahead_skip
        ) % self.path.size(0)
        # (np x lookahead x 2) - (np x 1 x 2)
        target_delta = self.path[next_k] - self.root_xz.unsqueeze(1)
        # Should be negative because going from global to local
        mat = self.get_rotation_matrix(-self.root_facing)
        # (np x 1 x 2 x 2) x (np x lookahead x 1 x 2)
        delta = (mat.unsqueeze(1) * target_delta.unsqueeze(2)).sum(dim=-1)
        return delta

    def get_observation_components(self):
        deltas = self.get_delta_to_k_targets()
        condition = self.get_cond_frame()
        return condition, deltas.flatten(start_dim=1, end_dim=2)

    def dump_additional_render_data(self):
        return {
            "extra.csv": {"header": "Target.X, Target.Z", "data": self.target[0]},
            "root0.csv": {
                "header": "Root.X, Root.Z, RootFacing",
                "data": torch.cat((self.root_xz, self.root_facing), dim=-1)[0],
            },
        }

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

        # Check if target is reached
        # Has to be done after new potentials are calculated
        target_dist = -self.linear_potential
        target_is_close = target_dist < 0.2
        self.reward.add_(target_is_close.float() * 10.0)

        #energy_penalty = self.calc_energy_penalty(next_frame)
        #self.reward.add_(energy_penalty * 0.75)

        #action_penalty = self.calc_action_penalty()
        #self.reward.add_(action_penalty * 0.5)

        # Need to reset target to next point in path
        # can only do this after progress is calculated
        self.reset_target()

        obs_components = list(self.get_observation_components())
        #obs_components[0] = obs_components[0].unsqueeze(0)
        #obs_components[1] = obs_components[1].unsqueeze(1)
        self.done.fill_(self.timestep >= self.max_timestep)
    
        # Everytime this function is called, should call render
        # otherwise the fps will be wrong
        self.render()

        return (
            torch.cat(obs_components, dim=-1),
            self.reward,
            self.done,
            {"reset": self.timestep >= self.max_timestep},
        )
    