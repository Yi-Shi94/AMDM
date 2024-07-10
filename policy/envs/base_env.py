import os.path as osp
import numpy as np
import gymnasium as gym

import torch
from render.realtime.mocap_renderer import PBLMocapViewer

coord_table = {'x':0, 'y':2, 'z':1}
def get_xyz_index(coord_order):
    return [coord_table[i] for i in coord_order]    

class EnvBase(gym.Env):
    def __init__(self, config, model, dataset, device):
        self.device = device
        self.is_rendered = config.get('is_rendered',True)
        self.num_parallel = config.get('num_parallel',1)
        self.num_parallel_test = config.get('num_parallel_test',1)

        self.frame_skip = config.get('frame_skip',1)
        self.max_timestep = config.get('max_timestep_test',2000) if self.is_rendered else config.get('max_timestep',1000//self.frame_skip)
        self.camera_tracking = config.get('camera_tracking',True)
        
        self.int_output_dir = config['int_output_dir']

        self.model = model
        self.dataset = dataset       

        self.frame_dim = dataset.frame_dim
        self.data_fps = dataset.fps
        self.sk_dict = dataset.skel_info
        
        self.links = dataset.links
        self.name_joint = dataset.joint_names
        self.offset_joint = dataset.joint_offset
        self.num_joint = len(self.name_joint)

        self.root_idx = dataset.root_idx
        self.foot_idx = dataset.foot_idx
        #self.head_idx = dataset.head_idx
                
        self.action_scale = config.get('action_scale',1)
        

        self.model_type = config['model_type']
        if config['model_type'] == 'amdm':
            
            self.action_step = config['action_step']
            self.use_action_mask = config.get('use_action_mask',False)
            
            if len(config['action_step']) == 0:
                self.action_step = list(range(model.T))
            self.action_mode = config['action_mode']
            
            
            if self.action_mode == 'loco':
                self.action_dim_per_step = 8
                
            elif self.action_mode == 'full':
                self.action_dim_per_step = self.frame_dim 
            
            self.action_dim = self.frame_dim + self.action_dim_per_step * len(self.action_step)
           
           
            self.extra_info = {'action_step':self.action_step,'action_mode':self.action_mode, 'is_train': not self.is_rendered}
            


        elif config['model_type'] == 'humor':   
            self.action_dim = model.action_dim #if hasattr(self.model,'action_dim') else 64
            self.extra_info = None
        
        elif config['model_type'] == 'mvae':   
            self.action_dim = model.action_dim #if hasattr(self.model,'action_dim') else 64
            self.extra_info = None

        else:
            self.action_dim = dataset.frame_dim
            self.extra_info = None

        if self.is_rendered:
            self.record_num_frames = np.zeros((self.num_parallel_test,))
            self.record_motion_seq = np.zeros((self.num_parallel_test, self.max_timestep, self.dataset.frame_dim))
            self.record_timestep = 0

        # history size is used to calculate floating as well
        self.history_size = 5
        self.num_condition_frames = 1
        self.history = torch.zeros(
            (self.num_parallel, self.history_size, self.frame_dim)
        ).to(self.device)

        self.steps_parallel = torch.zeros((self.num_parallel,1))

        self.root_facing = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.root_xz = torch.zeros((self.num_parallel, 2)).to(self.device)
        self.root_y = torch.zeros((self.num_parallel, 1)).to(self.device)

        self.reward = torch.zeros((self.num_parallel, 1)).to(self.device)
        self.potential = torch.zeros((self.num_parallel, 2)).to(self.device)
        self.done = torch.zeros((self.num_parallel, 1)).bool().to(self.device)
        self.early_stop = torch.zeros((self.num_parallel, 1)).bool().to(self.device)

        # used for reward-based early termination
        self.parallel_ind_buf = (
            torch.arange(0, self.num_parallel).long().to(self.device)
        )
        
        if self.is_rendered:
            self.viewer = PBLMocapViewer(
                    self,
                    num_characters=self.num_parallel,
                    target_fps=self.data_fps,
                    camera_tracking=self.camera_tracking,
                )
            
        high = np.inf * np.ones([self.action_dim])
        self.action_space = gym.spaces.Box(-high, high, dtype=np.float32)


    def save_motion(self):
        seqs = self.dataset.denorm_data(self.record_motion_seq)#.detach().cpu().numpy()
        for i in range(seqs.shape[0]):
            seq = seqs[i]
            xzs = self.dataset.x_to_trajs(seq)
            self.dataset.save_bvh(osp.join(self.int_output_dir,'out{}'.format(i)),seq)
            np.save(osp.join(self.int_output_dir,'traj{}'.format(i)),xzs)

        np.savez(osp.join(self.int_output_dir,'out.npz'), action=None, init_frame = self.init_frame.cpu().numpy(), nframe=self.record_timestep)


    def integrate_root_translation(self, pose):

        pose_denorm = self.dataset.denorm_data(pose, device=pose.device)

        mat = self.get_rotation_matrix(self.root_facing)
        displacement = (mat * pose_denorm[:, :2].unsqueeze(1)).sum(dim=2)
        dr = self.dataset.get_heading_dr(pose_denorm)[...,None]
        
        self.root_facing.add_(dr).remainder_(2 * np.pi)
        self.root_xz.add_(displacement)
        
        self.history = self.history.roll(1, dims=1)
        self.history[:, 0].copy_(pose)


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


    def get_cond_frame(self):
        condition = self.history[:, : self.num_condition_frames]
        b = condition.shape[0]
        condition = condition.view(b,-1)
        return condition

    def get_next_frame(self, action):
        self.action = action
        condition = self.get_cond_frame() 
        extra_info = self.extra_info
        
        with torch.no_grad():
            output = self.model.rl_step(condition, action, extra_info)
            
        if self.is_rendered:
            self.record_motion_seq[:,self.record_timestep,:]= output.cpu().detach().numpy()
            self.record_timestep += 1
            #if self.record_timestep % 90 == 0 and self.record_timestep != 0:
            #    self.save_motion()
            #sself.record_num_frames[:] += 1
        return output

    def reset(self, indices=None):
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

            # value bigger than contact_threshold
            #self.foot_pos_history.index_fill_(dim=0, index=indices, value=1)

        obs_components = self.get_observation_components()
        return torch.cat(obs_components, dim=1)


    def reset_initial_frames(self, frame_index=None):
        # Make sure condition_range doesn't blow up
        num_frame_used = len(self.valid_idx)
        num_init = self.num_parallel if frame_index is None else len(frame_index)

        #ensor([[537085]]) ==================
        #tensor([[2122372]]) ==================
        
        start_index = torch.randint(0,num_frame_used-1,(num_init,1))#2122372 #torch.randint(0,num_frame_used-1,(num_init,1)) 
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


    def calc_foot_slide(self):
        return 0
        '''
        foot_z = self.foot_pos_history[:, :, [2, 5]]
        # in_contact = foot_z < self.contact_threshold
        # contact_coef = in_contact.all(dim=1).float()
        # foot_xy = self.foot_pos_history[:, :, [[0, 1], [3, 4]]]
        # displacement = (
        #     (foot_xy.unsqueeze(1) - foot_xy.unsqueeze(2))
        #     .norm(dim=-1)
        #     .max(dim=1)[0]
        #     .max(dim=1)[0]
        # )
        # foot_slide = contact_coef * displacement

        displacement = self.foot_pos_history[:, 0] - self.foot_pos_history[:, 1]
        displacement = displacement[:, [[0, 1], [3, 4]]].norm(dim=-1)

        foot_slide = displacement.mul(
            2 - 2 ** (foot_z.max(dim=1)[0] / self.contact_threshold).clamp_(0, 1)
        )
        return foot_slide
        '''
    def calc_rigid_penalty(self):
        pass

    def calc_jittering(self):
        return 0

    def calc_energy_penalty(self, next_frame):
        vel_dim_lst = self.dataset.vel_dim_lst
        action_energy = (
            next_frame[:, [0, 1]].pow(2).sum(1)
            + next_frame[:, 2].pow(2)
            + next_frame[:,  vel_dim_lst[0]:  vel_dim_lst[1]].pow(2).mean(1)
        )
        return -0.8 * action_energy.unsqueeze(dim=1)

    def calc_action_penalty_reward(self):
        prob_energy = self.action.abs().mean(-1, keepdim=True)
        return -0.01 * prob_energy


    def step(self, action):
        next_frame = self.get_next_frame(action)
        obs, reward, done, info = self.calc_env_state(next_frame)
        return (obs, reward, done, info)
        
        
    def calc_env_state(self, next_frame, w=None):
        raise NotImplementedError

    def seed(self, seed=None):
        self.np_random, seed = gym.utils.seeding.np_random(seed)
        return [seed]

    def close(self):
        if self.is_rendered:
            self.viewer.close()

    def render(self, mode="human"):
        frame = self.dataset.denorm_data(self.history[:, 0], device=self.device).detach().cpu().numpy()
        if self.is_rendered:
            self.viewer.render(
                torch.tensor(self.dataset.x_to_jnts(frame, mode='angle'),device=self.device,dtype=self.root_facing.dtype),  # 0 is the newest
                self.root_facing,
                self.root_xz,
                0.0,  # No time in this env
                self.action,
            )