"""Joystick control: body-frame velocity commands on a frozen A-MDM prior, shared by PPO and Xbox playback.

Commands are forward m/s, right m/s, and clockwise yaw rad/s.
"""
import math
import numpy as np
import torch
import gymnasium as gym
from amdm_interactive.core.policy.envs.target_env import TargetEnv


class JoystickEnv(TargetEnv):
    def __init__(self, config, model, dataset, device):
        super().__init__(config, model, dataset, device)
        self.commands = torch.zeros(self.num_parallel, 3, device=device)
        self.command_age = torch.zeros(self.num_parallel, dtype=torch.long, device=device)
        self.external_command = False
        self.observation_dim = self.frame_dim + 3
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (self.observation_dim,), dtype=np.float32)
        self.root_action_mask = bool(config.get('root_action_mask', False))
        # Lying penalty, as in FacingTargetEnv: -w * clamp((1 - head height m) / 0.6, 0, 1).
        self.lying_weight = float(config.get('lying_weight', 0.))
        # command_dims 1: forward speed only (sideways and yaw-rate commands are 0, i.e. walk straight).
        self.command_dims = int(config.get('command_dims', 3))
        self.head_index = 3 + 3 * list(dataset.joint_names).index('Head') + 1

    def get_next_frame(self, action):
        # Optional: no direct root-velocity/yaw corrections in the correction slots (see FacingTargetEnv).
        if self.root_action_mask:
            action = action.clone().view(action.shape[0], -1, self.frame_dim)
            action[:, 1:, :3] = 0
            action = action.view(action.shape[0], -1)
        return super().get_next_frame(action)

    def sample_commands(self, ids):
        n = len(ids)
        self.commands[ids, 0] = torch.empty(n, device=self.device).uniform_(-1., 3.)
        self.commands[ids, 1] = torch.empty(n, device=self.device).uniform_(-1., 1.)
        # Sideways only at low forward speed (as in LAFAN): full +-1 m/s up to 1.5 m/s forward, none at 3.
        self.commands[ids, 1] *= ((3. - self.commands[ids, 0]) / 1.5).clamp(0., 1.)
        self.commands[ids, 2] = torch.empty(n, device=self.device).uniform_(-1.5, 1.5)
        if self.command_dims == 1:
            self.commands[ids, 1:] = 0
        self.commands[ids[torch.rand(n, device=self.device) < .15]] = 0
        self.command_age[ids] = torch.randint(60, 151, (n,), device=self.device)

    def set_command(self, command):
        self.external_command = True
        self.commands[:] = torch.as_tensor(command, device=self.device)

    def get_observation_components(self):
        return self.get_cond_frame(), self.commands / self.commands.new_tensor([3., 1., 1.5])

    def reset(self, indices=None):
        ids = torch.arange(self.num_parallel, device=self.device) if indices is None else indices
        self.root_facing[ids] = 0
        self.root_xz[ids] = 0
        self.reward[ids] = 0
        self.done[ids] = False
        self.timestep = 0
        self.substep = 0
        self.reset_initial_frames(None if indices is None else ids)
        if not self.external_command:
            self.sample_commands(ids)
        return torch.cat(self.get_observation_components(), dim=1)

    def reset_index(self, indices=None):
        return self.reset(indices)

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        self.timestep += 1
        self.integrate_root_translation(next_frame)
        raw = self.dataset.denorm_data(next_frame, device=self.device)
        planar = self.dataset.get_root_linear_planar_vel(raw) * self.data_fps
        yaw_rate = -self.dataset.get_heading_dr(raw) * self.data_fps
        measured = torch.stack((-planar[:, 1], planar[:, 0], yaw_rate), dim=-1)
        error = measured - self.commands
        self.reward[:] = (.7 * torch.exp(-error[:, :2].square().sum(-1) / .5)
                          + .3 * torch.exp(-error[:, 2].square() / .5))[:, None]
        self.reward -= self.lying_weight * ((1. - raw[:, self.head_index:self.head_index + 1]) / .6).clamp(0., 1.)
        self.command_age -= 1
        if not self.external_command:
            self.sample_commands(torch.where(self.command_age <= 0)[0])
        self.done.fill_(self.timestep >= self.max_timestep)
        return torch.cat(self.get_observation_components(), dim=1), self.reward, self.done, {'reset': self.timestep >= self.max_timestep}


class XboxCommand:
    """Xbox left stick: forward/right velocity; right horizontal stick: clockwise yaw."""
    def __init__(self, index=0, deadzone=.15, yaw_axis=2):  # this pad: 0,1 left; 2,3 right; 4,5 triggers
        import pygame
        self.pg = pygame
        pygame.display.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() <= index:
            raise RuntimeError('No Xbox-compatible controller detected')
        self.pad = pygame.joystick.Joystick(index)
        self.pad.init()
        self.instance = self.pad.get_instance_id()
        self.deadzone = deadzone
        self.yaw_axis = yaw_axis
        print(f'Xbox input: {self.pad.get_name()}', flush=True)

    def read(self):
        for event in self.pg.event.get():
            if event.type == self.pg.JOYDEVICEREMOVED and event.instance_id == self.instance:
                raise RuntimeError('Xbox controller disconnected')
        def axis(i):
            v = self.pad.get_axis(i)
            return np.sign(v) * max(0., (abs(v) - self.deadzone) / (1 - self.deadzone))
        forward = -axis(1)
        return [forward * (3. if forward >= 0 else 1.), axis(0), 1.5 * axis(self.yaw_axis)]

    def sticks(self):
        """Deadzoned (left x, left up, right x, right up), each in [-1, 1] (radial deadzone per stick)."""
        for event in self.pg.event.get():
            if event.type == self.pg.JOYDEVICEREMOVED and event.instance_id == self.instance:
                raise RuntimeError('Xbox controller disconnected')
        out = []
        for ax, ay in ((0, 1), (self.yaw_axis, self.yaw_axis + 1)):
            x, y = self.pad.get_axis(ax), -self.pad.get_axis(ay)
            r = math.hypot(x, y)
            k = 0. if r < self.deadzone else min(1., (r - self.deadzone) / (1 - self.deadzone)) / r
            out += [x * k, y * k]
        return out
