"""Trajectory following with a varying-speed path and a separate facing command, on a frozen A-MDM prior.

Each env gets its own path, generated at reset as 30 Hz waypoints starting at the character:
  speed     piecewise-constant targets from standstill to sprint (0-4 m/s), changed every 2-5 s and smoothed
            with a 2.5 m/s^2 acceleration limit;
  heading   piecewise-constant turn rates (some segments straight), limited to 3 m/s^2 lateral acceleration;
  facing    the body yaw to hold, as an offset from the path tangent: forward, sideways, backward or arbitrary.
            The offset is rate-limited (3 rad/s) and then clamped to a speed-dependent bound, so facing can only
            differ from the velocity direction when the commanded speed is low: any offset up to 1.5 m/s,
            shrinking linearly to 0 at 3 m/s (LAFAN has backward/sideways motion only at low speed).
The path starts at the character's root and leaves in a random direction, so the policy also learns to turn
onto it. Facing is world yaw; forward in the heading frame is local -y (same as TargetEnv/JoystickEnv).

Observation (285-D): normalized frame (267) | 7 path points at +0, 0.25, 0.5, 1, 1.5, 2, 2.5 s relative to
the root in the heading frame, m (14) | commanded velocity in the heading frame, m/s (2) | commanded facing as
a heading-frame unit vector (2).
Reward per step: 2 exp(-(d/0.5)^2) [d = distance to the current waypoint]
               + 1 exp(-|v - v_cmd|^2 / 0.6^2) + 1 exp(-(yaw error / 0.5)^2).
               - lying_weight * clamp((1 - head height) / 0.6, 0, 1)   [as in FacingTargetEnv]
An env terminates (and resets alone) when it is more than fail_distance (2 m) from the current waypoint.
"""
import math
import numpy as np
import torch
import gymnasium as gym
from amdm_interactive.core.policy.envs.target_env import TargetEnv

LOOKAHEAD_FRAMES = (0, 8, 15, 30, 45, 60, 75)


def wrap(a):
    return torch.remainder(a + math.pi, 2 * math.pi) - math.pi


class FacingPathEnv(TargetEnv):
    def __init__(self, config, model, dataset, device):
        super().__init__(config, model, dataset, device)
        self.speed_max = float(config.get('speed_max', 4.0))
        self.fail_distance = float(config.get('fail_distance', 2.0))
        self.root_action_mask = bool(config.get('root_action_mask', False))
        self.lying_weight = float(config.get('lying_weight', 0.))
        # 'free': facing offsets as above; 'forward': always face along the path (offset 0).
        self.facing_command = config.get('facing_command', 'free')
        if self.facing_command not in ('free', 'forward'):raise ValueError(self.facing_command)
        self.head_index = 3 + 3 * list(dataset.joint_names).index('Head') + 1
        self.lookahead = torch.tensor(LOOKAHEAD_FRAMES, device=device)
        self.path_len = self.max_timestep + LOOKAHEAD_FRAMES[-1] + 2
        n, length = self.num_parallel, self.path_len
        self.path = torch.zeros(n, length, 2, device=device)       # world xz waypoints, m
        self.path_vel = torch.zeros(n, length, 2, device=device)   # world velocity, m/s
        self.path_facing = torch.zeros(n, length, device=device)   # world facing yaw command, rad
        self.path_t = torch.zeros(n, dtype=torch.long, device=device)
        self.track_error = torch.zeros(n, 1, device=device)
        self.terms = torch.zeros(n, 3, device=device)  # position, velocity, facing reward terms (for diagnostics)
        self.observation_dim = self.frame_dim + 2 * len(LOOKAHEAD_FRAMES) + 4
        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)
        self.ids_all = torch.arange(n, device=device)
        # Path bank: generating a path is a ~380-step loop, so per-env resets draw from a bank that is
        # regenerated on every full reset (once per PPO rollout) instead of running the loop each time.
        self.bank_size = max(4 * n, 256)
        self.bank = None

    # ---- path generation -------------------------------------------------------------------------------
    def _segments(self, n, lo=60, hi=150):
        """Boolean (n, L): True on frames where a new piecewise-constant segment starts."""
        start = torch.zeros(n, self.path_len, dtype=torch.bool, device=self.device)
        nxt = torch.zeros(n, dtype=torch.long, device=self.device)
        rows = torch.arange(n, device=self.device)
        for _ in range(self.path_len // lo + 1):
            ok = nxt < self.path_len
            start[rows[ok], nxt[ok]] = True
            nxt = nxt + torch.randint(lo, hi + 1, (n,), device=self.device)
        return start

    def _hold(self, start, values):
        """Repeat values (n, L) from each segment start until the next one."""
        idx = torch.where(start, torch.arange(self.path_len, device=self.device).expand_as(start),
                          torch.zeros_like(start, dtype=torch.long))
        idx = idx.cummax(dim=1).values
        return values.gather(1, idx)

    def sample_paths(self, ids, start_speed=0., start_heading=None, start_offset=0., facing_offset=None):
        """Random paths for `ids`; start_* continue a previous path (speed m/s, heading and facing offset rad).

        facing_offset: None = random facing offsets (training); a number = hold that offset from the tangent."""
        n, length, dt, dev = len(ids), self.path_len, 1. / self.data_fps, self.device
        # Speed targets: standstill / slow / walk-jog / run-sprint.
        band = torch.multinomial(torch.tensor([.15, .35, .3, .2], device=dev), n * length, True).view(n, length)
        lo = torch.tensor([0., .2, 1.2, 2.5], device=dev)[band]
        hi = torch.tensor([.2, 1.2, 2.5, self.speed_max], device=dev)[band]
        target_speed = self._hold(self._segments(n), lo + (hi - lo) * torch.rand(n, length, device=dev))
        # Turn-rate targets, rad/s; 30% of segments straight.
        rate = torch.empty(n, length, device=dev).uniform_(-1.5, 1.5)
        rate[torch.rand(n, length, device=dev) < .3] = 0
        turn_rate = self._hold(self._segments(n), rate)
        # Facing offsets from the path tangent.
        kind = torch.multinomial(torch.tensor([.55, .15, .1, .2], device=dev), n * length, True).view(n, length)
        side = torch.where(torch.rand(n, length, device=dev) < .5, -1., 1.)
        offset = torch.stack((torch.zeros(n, length, device=dev), side * math.pi / 2,
                              torch.full((n, length), math.pi, device=dev),
                              torch.empty(n, length, device=dev).uniform_(-math.pi, math.pi)), -1)
        offset = self._hold(self._segments(n), offset.gather(-1, kind[..., None]).squeeze(-1))
        if self.facing_command == 'forward':
            offset.zero_()
        elif facing_offset is not None:
            offset.fill_(float(facing_offset))

        speed = torch.full((n,), float(start_speed), device=dev)
        heading = (torch.empty(n, device=dev).uniform_(-math.pi, math.pi) if start_heading is None
                   else torch.full((n,), float(start_heading), device=dev))
        pos = torch.zeros(n, 2, device=dev)
        rel = torch.full((n,), float(start_offset), device=dev)  # facing offset from the tangent, rate limited
        path = torch.zeros(n, length, 2, device=dev)
        vel = torch.zeros(n, length, 2, device=dev)
        face = torch.zeros(n, length, device=dev)
        for i in range(length):
            speed = speed + (target_speed[:, i] - speed).clamp(-2.5 * dt, 2.5 * dt)
            max_rate = 3. / speed.clamp_min(1.)
            heading = heading + turn_rate[:, i].clamp(-max_rate, max_rate) * dt
            direction = torch.stack((heading.cos(), heading.sin()), -1)
            vel[:, i] = speed[:, None] * direction
            if i:
                pos = pos + vel[:, i] * dt
            path[:, i] = pos
            # Rate-limit the offset, then clamp it to the speed bound (hard guarantee at every frame).
            rel = rel + wrap(offset[:, i] - rel).clamp(-3. * dt, 3. * dt)
            limit = math.pi * ((3. - speed) / 1.5).clamp(0., 1.)
            rel = torch.maximum(torch.minimum(rel, limit), -limit)
            face[:, i] = heading + rel
        return path, vel, face

    def draw_paths(self, ids):
        if self.bank is None or len(ids) == self.num_parallel:
            self.bank = self.sample_paths(torch.arange(self.bank_size, device=self.device))
        pick = torch.randint(0, self.bank_size, (len(ids),), device=self.device)
        return tuple(b[pick] for b in self.bank)

    # ---- world/heading-frame helpers -----------------------------------------------------------------------
    def to_heading_frame(self, world):
        """world (n, k, 2) vectors -> heading frame (same rotation TargetEnv uses for its target delta)."""
        mat = self.get_rotation_matrix(-self.root_facing)
        return (mat.unsqueeze(1) * world.unsqueeze(2)).sum(dim=-1)

    def body_yaw(self):
        """World yaw of the body forward axis (heading-frame -y)."""
        fwd = self.to_heading_frame_inverse(torch.tensor([0., -1.], device=self.device).expand(self.num_parallel, 1, 2))
        return torch.atan2(fwd[:, 0, 1], fwd[:, 0, 0])

    def to_heading_frame_inverse(self, local):
        mat = self.get_rotation_matrix(self.root_facing)
        return (mat.unsqueeze(1) * local.unsqueeze(2)).sum(dim=-1)

    def current(self, field):
        return field[self.ids_all, self.path_t]

    # ---- env API -------------------------------------------------------------------------------------
    def get_observation_components(self):
        idx = (self.path_t[:, None] + self.lookahead).clamp(max=self.path_len - 1)
        points = self.path.gather(1, idx[..., None].expand(-1, -1, 2)) - self.root_xz[:, None]
        local_points = self.to_heading_frame(points).flatten(1)
        local_vel = self.to_heading_frame(self.current(self.path_vel)[:, None])[:, 0]
        cmd = self.current(self.path_facing)
        local_face = self.to_heading_frame(torch.stack((cmd.cos(), cmd.sin()), -1)[:, None])[:, 0]
        return self.get_cond_frame(), torch.cat((local_points, local_vel, local_face), 1)

    def reset_target(self, indices=None, location=None):
        pass

    def calc_potential(self):
        pass

    def reset(self, indices=None):
        ids = self.ids_all if indices is None else indices
        if indices is None:
            self.timestep = 0
            self.substep = 0
        self.root_xz[ids] = 0
        self.reward[ids] = 0
        self.done[ids] = False
        self.path_t[ids] = 0
        self.reset_initial_frames(None if indices is None else ids)
        # The character keeps its spawn heading (0); the path leaves from it in a random direction.
        self.root_facing[ids] = 0
        path, vel, face = self.draw_paths(ids)
        self.path[ids], self.path_vel[ids], self.path_facing[ids] = path, vel, face
        return torch.cat(self.get_observation_components(), dim=1)

    def reset_index(self, indices=None):
        return self.reset(indices)

    def reset_initial_frames(self, frame_index=None):
        num = self.num_parallel if frame_index is None else len(frame_index)
        start = self.valid_idx[torch.randint(0, len(self.valid_idx) - 1, (num, 1))]
        data = torch.as_tensor(self.dataset.motion_flattened[start], device=self.device, dtype=self.history.dtype)
        if frame_index is None:
            self.history[:, :self.num_condition_frames] = data
        else:
            self.history[frame_index, :self.num_condition_frames] = data

    def get_next_frame(self, action):
        if self.root_action_mask:
            action = action.clone().view(action.shape[0], -1, self.frame_dim)
            action[:, 1:, :3] = 0
            action = action.view(action.shape[0], -1)
        return super().get_next_frame(action)

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        self.timestep += 1
        old_facing = self.root_facing.clone()
        self.integrate_root_translation(next_frame)
        self.path_t = (self.path_t + 1).clamp(max=self.path_len - 1)
        raw = self.dataset.denorm_data(next_frame, device=self.device)
        local_vel = self.dataset.get_root_linear_planar_vel(raw) * self.data_fps
        # Same rotation integrate_root_translation used for this frame's displacement.
        mat = self.get_rotation_matrix(old_facing)
        world_vel = (mat * local_vel.unsqueeze(1)).sum(dim=2)

        d = (self.root_xz - self.current(self.path)).norm(dim=1, keepdim=True)
        vel_err = (world_vel - self.current(self.path_vel)).square().sum(1, keepdim=True)
        yaw_err = wrap(self.body_yaw() - self.current(self.path_facing))[:, None]
        self.terms = torch.cat((torch.exp(-(d / .5).square()), torch.exp(-vel_err / .36),
                                torch.exp(-(yaw_err / .5).square())), 1)
        self.track_error = d
        self.lying_term = ((1. - raw[:, self.head_index:self.head_index + 1]) / .6).clamp(0., 1.)
        self.reward = (2 * self.terms[:, :1] + self.terms[:, 1:2] + self.terms[:, 2:3]
                       - self.lying_weight * self.lying_term)
        self.done = (d > self.fail_distance) | (self.timestep >= self.max_timestep)
        obs = torch.cat(self.get_observation_components(), dim=1)
        if not (torch.isfinite(obs).all() and torch.isfinite(self.reward).all()):
            raise RuntimeError(f'Nonfinite path env state at step {self.timestep}')
        self.render()
        return obs, self.reward, self.done, {'reset': self.timestep >= self.max_timestep}
