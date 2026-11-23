"""Upstream TargetEnv plus a facing term that rewards pointing the body's forward axis at the target.

Forward in the heading frame is local -y (same convention as JoystickEnv: forward = -planar[1]).
Reward per step = upstream (2 exp(-d/2), or 5 on reach) + facing_weight * term, where term is
  'cos':         cos(angle to target)                      (pays for standing and turning)
  'forward_vel': clamp(v_forward, 0, 1.5 m/s) * cos(angle)  (pays only for walking forward at the target)
plus progress_weight * (approach speed toward the current target, m/s); upstream computes this but never adds it.
progress_cap (m/s) clips the approach speed from above before weighting (moving away stays fully penalised): without
  it the progress term keeps paying for sprinting and lunging at the target, which degraded motion quality.
backward_weight penalises backward root speed: -backward_weight * max(0, -v_forward) (m/s).
reach_radius replaces upstream's hardcoded 0.4 m reach threshold.
distance_weight scales upstream's dense closeness term 2 exp(-d/2) (default 2 = upstream) and reach_bonus replaces its
  per-reach 5. A dense closeness term plus respawn-on-reach makes orbiting just outside the reach radius pay more than
  reaching, so use progress_weight (telescoping, orbiting earns nothing) with a small distance_weight and a large bonus.
reaches / reach_steps count reached targets and env steps since the trainer last read them (logged as reaches per minute).
lying_weight penalises lying down: -lying_weight * clamp((1.0 - head height) / 0.6, 0, 1), i.e. nothing with the head
  above 1 m (standing 1.4-1.6 m, crouch ~1 m in LAFAN), full penalty at 0.4 m and below (lying ~0.2-0.3 m).
retarget_rate (per second) moves the current target to a new random spot before it is reached (Poisson), so the
  policy learns to re-plan when the goal changes (as when a user clicks a new target).
root_action_mask zeroes the correction slots' root channels (planar velocity + yaw rate), so the policy cannot
push the root directly and has to steer through the body pose; the initial-noise slot is left alone.
"""
import torch
from amdm_interactive.core.policy.envs.target_env import TargetEnv


class FacingTargetEnv(TargetEnv):
    def __init__(self, config, model, dataset, device):
        super().__init__(config, model, dataset, device)
        self.facing_weight = float(config.get('facing_weight', 0.))
        self.facing_mode = config.get('facing_mode', 'cos')
        if self.facing_mode not in ('cos', 'forward_vel'):raise ValueError(self.facing_mode)
        self.facing_cos = torch.zeros(self.num_parallel, 1, device=device)
        self.facing_term = torch.zeros(self.num_parallel, 1, device=device)
        self.progress_weight = float(config.get('progress_weight', 0.))
        self.progress_speed = torch.zeros(self.num_parallel, 1, device=device)
        self.progress_cap = config.get('progress_cap', None)
        self.root_action_mask = bool(config.get('root_action_mask', False))
        self.backward_weight = float(config.get('backward_weight', 0.))
        self.reach_radius = float(config.get('reach_radius', 0.4))
        self.distance_weight = float(config.get('distance_weight', 2.))
        self.reach_bonus = float(config.get('reach_bonus', 5.))
        self.reaches = 0
        self.reach_steps = 0
        self.backward_speed = torch.zeros(self.num_parallel, 1, device=device)
        self.lying_weight = float(config.get('lying_weight', 0.))
        self.retarget_rate = float(config.get('retarget_rate', 0.))
        self.lying_term = torch.zeros(self.num_parallel, 1, device=device)
        self.head_index = 3 + 3 * list(dataset.joint_names).index('Head') + 1  # joint positions start at 3, y-up
        self.hold_target = False  # viewer: keep a user-placed target after it is reached

    def get_next_frame(self, action):
        if self.root_action_mask:
            action = action.clone().view(action.shape[0], -1, self.frame_dim)
            action[:, 1:, :3] = 0
            action = action.view(action.shape[0], -1)
        return super().get_next_frame(action)

    def target_facing_cos(self):
        _, local = self.get_observation_components()
        return (-local[:, 1:2]) / local.norm(dim=1, keepdim=True).clamp_min(1e-6)

    def calc_progress_reward(self):
        # Runs after root integration and before a reached target is resampled.
        progress = super().calc_progress_reward()
        self.progress_speed = progress * self.data_fps
        if self.progress_cap is not None:
            self.progress_speed = self.progress_speed.clamp(max=float(self.progress_cap))
        self.facing_cos = self.target_facing_cos()
        raw = self.dataset.denorm_data(self.next_frame, device=self.device)
        forward = -self.dataset.get_root_linear_planar_vel(raw)[:, 1:2] * self.data_fps
        self.backward_speed = (-forward).clamp_min(0.)
        self.lying_term = ((1. - raw[:, self.head_index:self.head_index + 1]) / .6).clamp(0., 1.)
        if self.facing_mode == 'cos':
            self.facing_term = self.facing_cos
        else:
            self.facing_term = forward.clamp(0., 1.5) * self.facing_cos
        return progress

    def calc_env_state(self, next_frame):
        # Upstream TargetEnv.calc_env_state with the reach radius made configurable.
        self.next_frame = next_frame
        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip
        self.integrate_root_translation(next_frame)
        self.calc_progress_reward()
        target_is_close = -self.linear_potential < self.reach_radius
        self.reward.copy_(self.distance_weight * torch.exp(0.5 * self.linear_potential))
        self.reward[target_is_close] = self.reach_bonus
        self.reaches += int(target_is_close.sum())
        self.reach_steps += 1
        if target_is_close.any() and not self.hold_target:
            self.reset_target(indices=self.parallel_ind_buf.masked_select(target_is_close.squeeze(1)))
        if self.retarget_rate > 0 and not self.hold_target:
            move = (torch.rand(self.num_parallel, device=self.device) < self.retarget_rate / self.data_fps) & ~target_is_close.squeeze(1)
            if move.any():
                self.reset_target(indices=self.parallel_ind_buf.masked_select(move))
        obs = torch.cat(self.get_observation_components(), dim=1)
        self.done.fill_(self.timestep >= self.max_timestep)
        self.render()
        reward, done, info = self.reward, self.done, {'reset': self.timestep >= self.max_timestep}
        reward.add_(self.facing_weight * self.facing_term + self.progress_weight * self.progress_speed
                    - self.backward_weight * self.backward_speed - self.lying_weight * self.lying_term)
        if not (torch.isfinite(obs).all() and torch.isfinite(reward).all()):
            bad = (~torch.isfinite(obs)).any(1) | (~torch.isfinite(reward)).squeeze(1)
            raise RuntimeError(f'Nonfinite env state at step {self.timestep}: envs {bad.nonzero().flatten().tolist()[:8]}, '
                               f'obs bad dims {(~torch.isfinite(obs[bad])).any(0).nonzero().flatten().tolist()[:12]}, '
                               f'next_frame finite {bool(torch.isfinite(next_frame[bad]).all())}')
        return obs, reward, done, info
