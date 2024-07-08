import policy.envs.base_env as base_env

from render.realtime.mocap_renderer import PBLMocapViewer
import os
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym

class HumanMazeEnv(base_env.EnvBase):
   def __init__(self, config, model, target_model, dataset, device):

        super().__init__(self, config, model,  dataset, device)

        #basepath = os.path.normpath if os.path.isdir(pose_vae_path) else os.path.dirname
        #policy_path = os.path.join(basepath(pose_vae_path), "con_TargetEnv-v0.pt")
        #self.target_controller = torch.load(policy_path, map_location=self.device).actor
        self.target_controller = target_model
        self.action_dim = 2
        high = np.inf * np.ones([self.action_dim])
        self.action_space = gym.spaces.Box(-high, high, dtype=np.float32)

        self.max_timestep = 1500
        self.max_reward = 2048.0
        self.arena_bounds = (-100.0, 100.0)
        self.ep_reward = torch.zeros_like(self.reward)

        # coverage to encourage exploration
        map_shape = (self.num_parallel, 1024)
        self.coverage_map = torch.zeros(map_shape).bool().to(self.device)
        self.scale = np.sqrt(self.coverage_map.size(-1)) / (
            self.arena_bounds[1] - self.arena_bounds[0]
        )

        # Simple vision system
        limit = 60 / 180 * np.pi
        self.vision_distance = 100
        self.num_eyes = 16
        self.vision = torch.empty((self.num_parallel, self.num_eyes, 1)).to(self.device)
        self.vision.fill_(self.vision_distance)
        self.fov = torch.linspace(-limit, limit, self.num_eyes).to(self.device)

        # Overwrite, always start with same pose
        self.start_indices.fill_(0)

        base_obs_dim = (
            # condition + vision + coverage_map + normalized_root
            (self.frame_dim * self.num_condition_frames)
            + self.num_eyes
        )

        self.observation_dim = base_obs_dim
        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)

        self.create_simulation_world()

    def create_simulation_world(self):

        w2 = (self.arena_bounds[1] - self.arena_bounds[0]) / 2
        w4 = w2 / 2
        w8 = w4 / 2

        self.walls_start = torch.tensor(
            [
                [-w2, +w2],  # top left
                [+w2, +w2],  # top right
                [+w2, -w2],  # bottom right
                [-w2, -w2],  # bottom left
                [-w2, -w4 - w8],
                [-w4 - w8, -w4],
                [-w4 - w8, -w4],
                [-w4, -w8],
                [w4 + w8, -w8],
                [w4 + w8, -w8],
                [0, -w8],
                [w4 + w8, w4 + w8],
                [+w4, 0],
                [+w8, 0],
                [0, 0],
                [-w8, 0],
            ]
        )
        self.walls_end = torch.tensor(
            [
                [+w2, +w2],  # top right
                [+w2, -w2],  # bottom right
                [-w2, -w2],  # bottom left
                [-w2, +w2],  # top left
                [w4 + w8, -w4 - w8],
                [w2, -w4],
                [-w4 - w8, w2 - w8],
                [-w4, w2 - w8],
                [w4 + w8, w2 - w8],
                [w8, -w8],
                [-w4, -w8],
                [-w4, w4 + w8],
                [+w4, w4],
                [+w8, w4],
                [0, w4],
                [-w8, w4],
            ]
        )
        self.wall_thickness = 0.5

        if self.is_rendered:
            from common.bullet_objects import Rectangle, VSphere

            # Disable rendering during creation
            self.viewer._p.configureDebugVisualizer(
                self.viewer._p.COV_ENABLE_RENDERING, 0
            )

            half_height = 3.0

            for start, end in zip(self.walls_start, self.walls_end):
                delta = end - start
                half_length = delta.norm() / 2

                wall = Rectangle(
                    self.viewer._p,
                    half_length * FOOT2METER,
                    self.wall_thickness * FOOT2METER,
                    half_height * FOOT2METER,
                    max=True,
                    replica=1,
                )

                centre = F.pad((start + end) / 2, pad=[0, 1], value=half_height)
                centre *= FOOT2METER
                direction = float(torch.atan2(delta[1], delta[0]))
                quat = self.viewer._p.getQuaternionFromEuler([0, 0, direction])
                wall.set_positions([centre.numpy()], [quat])

            # re-enable rendering
            self.viewer._p.configureDebugVisualizer(
                self.viewer._p.COV_ENABLE_RENDERING, 1
            )

            # Need to do this else reset() doesn't work
            self.viewer.state_id = self.viewer._p.saveState()

        # Save to GPU for faster calculation later
        self.walls_start = self.walls_start.to(self.device)
        self.walls_end = self.walls_end.to(self.device)
        self.walls_mid = (self.walls_start + self.walls_end) / 2
        self.walls_hl = (self.walls_start - self.walls_end).norm(dim=-1) / 2
        delta = self.walls_start - self.walls_end
        self.walls_direction = torch.atan2(delta[:, 1], delta[:, 0])

    def reset_initial_frames(self, indices=None):

        # Newer has smaller index (ex. index 0 is newer than 1)
        condition_range = (
            self.start_indices.repeat((self.num_condition_frames, 1)).t()
            + torch.arange(self.num_condition_frames - 1, -1, -1).long()
        )

        condition = self.mocap_data[condition_range]

        if indices is None:
            self.history[:, : self.num_condition_frames].copy_(condition)
        else:
            self.history[:, : self.num_condition_frames].index_copy_(
                dim=0, index=indices, source=condition[indices]
            )

    def reset_root_state(self, indices=None, deterministic=False):
        reset_bound = (0.9 * self.arena_bounds[0], 0.9 * self.arena_bounds[1])
        if indices is None:
            if deterministic:
                self.root_facing.fill_(0)
                self.root_xz.fill_(0)
            else:
                self.root_facing.uniform_(0, 2 * np.pi)
                self.root_xz.uniform_(*reset_bound)
        else:
            if deterministic:
                self.root_facing.index_fill_(dim=0, index=indices, value=0)
                self.root_xz.index_fill_(dim=0, index=indices, value=0)
            else:
                new_facing = self.root_facing[indices].uniform_(0, 2 * np.pi)
                new_xz = self.root_xz[indices].uniform_(*reset_bound)
                self.root_facing.index_copy_(dim=0, index=indices, source=new_facing)
                self.root_xz.index_copy_(dim=0, index=indices, source=new_xz)

        if not deterministic:
            x, y, _ = extract_joints_xyz(self.history[:, 0], *self.joint_indices, dim=1)
            while True:
                joints_pos = self.root_xz.unsqueeze(1) + torch.stack((x, y), dim=-1)
                collision = (
                    self.calc_collision_with_walls(joints_pos)
                    .any(dim=-1, keepdim=True)
                    .squeeze(-1)
                )
                if collision.any():
                    new_xz = self.root_xz[collision].uniform_(*self.arena_bounds)
                    self.root_xz[collision] = new_xz
                else:
                    break


    def reset(self, indices=None):
        if indices is None:
            self.timestep = 0
            self.substep = 0
            self.root_facing.fill_(0)
            self.reward.fill_(0)
            self.ep_reward.fill_(0)
            self.done.fill_(False)
            self.coverage_map.fill_(False)

            # value bigger than contact_threshold
            self.foot_pos_history.fill_(1)
        else:
            self.root_facing.index_fill_(dim=0, index=indices, value=0)
            self.reward.index_fill_(dim=0, index=indices, value=0)
            self.ep_reward.index_fill_(dim=0, index=indices, value=0)
            self.done.index_fill_(dim=0, index=indices, value=False)
            self.coverage_map.index_fill_(dim=0, index=indices, value=False)

            # value bigger than contact_threshold
            self.foot_pos_history.index_fill_(dim=0, index=indices, value=1)

        self.reset_initial_frames(indices)
        self.reset_root_state(indices)

        self.calc_vision_state()
        obs_components = self.get_observation_components()
        return torch.cat(obs_components, dim=1)

    def step(self, action: torch.Tensor):
        # This one is arena size
        hl_action = action * 40.0
        condition = self.get_vae_condition(normalize=False)
        with torch.no_grad():
            ll_action = self.target_controller(torch.cat((condition, hl_action), dim=1))
            ll_action *= self.action_scale
        next_frame = self.get_vae_next_frame(ll_action)
        state = self.calc_env_state(next_frame[:, 0])
        return state

    def get_observation_components(self):
        condition = self.get_vae_condition(normalize=False)
        vision = self.vision.flatten(start_dim=1, end_dim=2)
        base_obs_component = (condition, vision)
        return base_obs_component

    def dump_additional_render_data(self):
        return {
            "root0.csv": {
                "header": "Root.X, Root.Z, RootFacing",
                "data": torch.cat((self.root_xz, self.root_facing), dim=-1)[0],
            },
            "walls.csv": {
                "header": "Wall.X, Wall.Z, Wall.HalfLength, Wall.Angle",
                "data": torch.cat(
                    (
                        self.walls_mid,
                        self.walls_hl.unsqueeze(-1),
                        self.walls_direction.unsqueeze(-1),
                    ),
                    dim=-1,
                ),
                "once": True,
            },
        }

    def calc_collision_with_walls(self, joints_pos, radius=0.01):
        # (num_character, num_walls, num_joins, 2)
        p1 = self.walls_start[None, :, None, :]
        p2 = self.walls_end[None, :, None, :]
        c = joints_pos.unsqueeze(1)
        # size of each joint is defined in mocap_renderer
        # need to account for joint size and wall thickness
        d, mask = line_to_point_distance(p1, p2, c)
        mask = mask * (d < (self.wall_thickness + radius * METER2FOOT))
        return mask.any(dim=-1).any(dim=-1, keepdim=True)

    def calc_distance_to_walls(self):
        angles = (self.fov - self.root_facing).unsqueeze(-1)
        directions = torch.cat([angles.cos(), angles.sin()], dim=2)

        # (num_character, num_eyes, num_walls, 2)
        p0 = self.walls_start[None, None, :, :]
        p1 = self.walls_end[None, None, :, :]
        p2 = self.root_xz[:, None, None, :]
        p3 = p2 + self.vision_distance * directions.unsqueeze(2)

        p3p2 = p3 - p2
        p1p0 = p1 - p0

        a = p3p2.select(-1, 0) * p1p0.select(-1, 0)
        b = p3p2.select(-1, 0) * p1p0.select(-1, 1)
        c = p3p2.select(-1, 1) * p1p0.select(-1, 0)

        d = a * (p0.select(-1, 1) - p2.select(-1, 1))
        e = b * p0.select(-1, 0)
        f = c * p2.select(-1, 0)

        x = (d - e + f) / (c - b)
        m = p3p2.select(-1, 1) / p3p2.select(-1, 0)
        y = m * x + (p2.select(-1, 1) - m * p2.select(-1, 0))

        solution = torch.stack((x, y), dim=-1)

        vector1 = -self.vision_distance * directions.unsqueeze(2)
        vector2 = solution - p3
        vector3 = solution - p2
        cosine1 = (vector2 * vector1).sum(dim=-1)
        cosine2 = (vector3 * -vector1).sum(dim=-1)

        distance = vector3.norm(dim=-1)
        mask = (
            ((solution - self.walls_mid).norm(dim=-1) < self.walls_hl)
            * (vector3.norm(dim=-1) < self.vision_distance)
            * (cosine1 > 0)
            * (cosine2 > 0)
        )

        self.vision[:, :, 0].copy_(
            distance.masked_fill(~mask, self.vision_distance).min(dim=-1)[0]
        )

    def calc_coverage_reward(self):
        # Exploration reward
        normalized_xz = (self.root_xz - self.arena_bounds[0]) * self.scale
        map_coordinate = (
            (
                normalized_xz[:, 0] * (np.sqrt(self.coverage_map.size(-1)) - 1)
                + normalized_xz[:, 1]
            )
            .long()
            .clamp(min=0, max=self.coverage_map.size(1) - 1)
        )

        old_coverage_count = self.coverage_map.sum(dim=-1)
        self.coverage_map[self.parallel_ind_buf, map_coordinate] = True
        coverage_bonus = self.coverage_map.sum(dim=-1) - old_coverage_count
        self.reward.add_(coverage_bonus.float().unsqueeze(-1) * 0.5)

    def calc_vision_state(self):
        # Two functions calculate intersection differently
        self.calc_distance_to_walls()
        # self.draw_debug_lines()
        # Walls can block line of sight, others cannot
        # mask = self.vision[:, :, [0]] < self.vision
        # self.vision[mask] = self.vision_distance

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        is_external_step = self.substep == 0

        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip

        self.integrate_root_translation(next_frame)

        # (num_character, 1, 2) - (num_character, num_pellets, 2)
        x, y, _ = extract_joints_xyz(next_frame, *self.joint_indices, dim=1)
        joints_pos = self.root_xz.unsqueeze(1) + torch.stack((x, y), dim=-1)

        collision = self.calc_collision_with_walls(joints_pos).any(dim=-1, keepdim=True)
        self.calc_vision_state()

        self.reward.fill_(0)

        self.calc_coverage_reward()

        obs_components = self.get_observation_components()
        self.done.copy_(collision + (self.timestep >= self.max_timestep))

        self.render()

        return (
            torch.cat(obs_components, dim=1),
            self.reward,
            self.done,
            {"reset": self.timestep >= self.max_timestep},
        )

    def draw_debug_lines(self):
        if not self.is_rendered:
            return

        ray_from = self.root_xz.unsqueeze(1).expand(
            self.num_parallel, self.num_eyes, self.root_xz.size(-1)
        )

        angles = (self.fov - self.root_facing).unsqueeze(-1)
        directions = torch.cat([angles.cos(), angles.sin()], dim=2)
        deltas = self.vision.min(dim=-1)[0].unsqueeze(-1) * directions
        ray_to = ray_from + deltas

        ray_from = (
            (F.pad(ray_from, pad=[0, 1], value=3) * FOOT2METER)
            .flatten(0, 1)
            .cpu()
            .numpy()
        )
        ray_to = (
            (F.pad(ray_to, pad=[0, 1], value=3) * FOOT2METER)
            .flatten(0, 1)
            .cpu()
            .numpy()
        )

        if not hasattr(self, "ray_ids"):
            self.ray_ids = [
                self.viewer._p.addUserDebugLine((0, 0, 0), (1, 0, 0), (1, 0, 0))
                for i in range(self.num_parallel * self.num_eyes)
            ]

        for i, (start, end, dist) in enumerate(
            zip(ray_from, ray_to, self.vision.min(dim=-1)[0].flatten())
        ):
            rayHitColor = [1, 0, 0]
            rayMissColor = [0, 1, 0]
            colour = rayHitColor if dist < self.vision_distance else rayMissColor
            self.viewer._p.addUserDebugLine(
                start, end, colour, replaceItemUniqueId=self.ray_ids[i]
            )

    def render(self, mode="human"):
        if self.is_rendered:
            self.viewer.render(
                self.history[:, 0],  # 0 is the newest
                self.root_facing,
                self.root_xz,
                0.0,  # No time in this env
                self.action,
            )

        # if self.is_rendered and self.timestep % 15 == 0:
        #     self.viewer.duplicate_character()
