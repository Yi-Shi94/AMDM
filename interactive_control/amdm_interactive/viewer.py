"""Real-time MuJoCo viewer for a frozen A-MDM prior and its PPO controllers, on an SMPL body.

Run from the project root (interactive_control/ in the AMDM repo):
    python -m amdm_interactive.viewer                                          # prior only (unconditional)
    python -m amdm_interactive.viewer --controller output/interactive/target/policy.pth
    python -m amdm_interactive.viewer --controller output/interactive/path/policy.pth
    python -m amdm_interactive.viewer --controller output/interactive/joystick/policy.pth --xbox

The task is read from args.json next to the policy. Target and path open a bird's-eye map window: click to
place targets, or drag to draw a path (see README.md for all controls). Keys in the MuJoCo window:
R reset, Space pause, C swap SMPL mesh / capsule person, E toggle EMA weights, G play the ground-truth seed clip.

Body (--body): 'smpl' = the SMPL-H template fitted to LAFAN proportions (amdm_interactive/fit_smpl_shape.py),
'capsule' = the primitive capsule person of the GenerativeWBC dodge task (no download). The default is smpl when
the fitted template exists (C swaps to the capsule person and back), else capsule only. Frames: the env plane (x, z) maps to viewer world (x, -y); viewer-world body yaw is
pi/2 - root_facing.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import time
import types
from pathlib import Path

import numpy as np
import torch
import yaml

from amdm_interactive.capsule_body import CapsuleBody
from amdm_interactive.smpl_body import SMPLMujocoBody, SMPL_SOURCE, PARENTS, _align

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIOR = ROOT / 'output/base/amdm_lafan1_t16/model_param.pth'
# BVH y-up (x, y, z) -> MuJoCo z-up world.
SOURCE_TO_WORLD = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])
# SMPL24 joint order -> LAFAN22 joint order. The extra palm joints inherit the wrist orientation.
MAP = np.array([0, 1, 5, 9, 2, 6, 10, 3, 7, 11, 4, 8, 12, 14, 18, 13, 15, 19, 16, 20, 17, 21, 17, 21])


def wrap_angle(q):
    return (q + math.pi) % (2 * math.pi) - math.pi


# ---- LAFAN -> SMPL retargeting -------------------------------------------------------------------------------
def proper_alignment(target, source):
    """Rotation taking target rest-bone vectors onto source rest-bone vectors (Kabsch, no reflection)."""
    a = np.asarray(target); b = np.asarray(source)
    a = a / np.linalg.norm(a, axis=-1, keepdims=True); b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    u, _, vt = np.linalg.svd(b.T @ a)
    return u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt


class SMPLRetarget:
    """Maps LAFAN global joint rotations onto the SMPL skeleton, calibrated on a near-T-pose LAFAN frame."""

    def __init__(self, rest, source_offsets, source_parents, bind_rotations=None, bind_positions=None):
        self.rest = np.asarray(rest)
        self.offsets = np.zeros_like(rest)
        source = np.zeros((22, 3)); source_offsets = np.asarray(source_offsets)
        for i, p in enumerate(source_parents):
            source[i] = source_offsets[i] if p < 0 else source[p] + source_offsets[i]
        self.source_hip_center = (source[1] + source[5]) / 2
        self.target_hip_center = (rest[1] + rest[2]) / 2 - rest[0]
        src, dst = [], []
        for i, p in enumerate(PARENTS):
            if p < 0:
                continue
            self.offsets[i] = rest[i] - rest[p]
            if MAP[i] != MAP[p]:
                src.append(source[MAP[i]] - source[MAP[p]]); dst.append(self.offsets[i])
        base = proper_alignment(dst, src)
        if bind_positions is not None:
            def basis(j, left, right, neck):
                side = j[left] - j[right]; side /= np.linalg.norm(side)
                up = j[neck] - j[0]; up -= side * np.dot(up, side); up /= np.linalg.norm(up)
                return np.stack((np.cross(side, up), side, up), axis=-1)
            base = basis(bind_positions, 1, 5, 12) @ basis(rest, 1, 2, 12).T
        posed_source = source if bind_positions is None else bind_positions
        self.bind = np.repeat(base[None], 24, axis=0)
        for i in range(24):
            children = [j for j, p in enumerate(PARENTS) if p == i and MAP[j] != MAP[i]]
            if len(children) > 1:
                self.bind[i] = proper_alignment([self.offsets[j] for j in children],
                                                [posed_source[MAP[j]] - posed_source[MAP[i]] for j in children])
            elif children:
                j = children[0]
                self.bind[i] = _align(base @ self.offsets[j], posed_source[MAP[j]] - posed_source[MAP[i]]).as_matrix() @ base
            if bind_rotations is not None:
                # LAFAN spine/clavicle offsets use different anatomical axes: keep SMPL's neutral torso at the
                # reference pose instead of introducing a compensating chest/neck bend.
                if i in (0, 3, 6, 9, 12, 13, 14, 15):
                    self.bind[i] = base
                self.bind[i] = bind_rotations[MAP[i]].T @ self.bind[i]
            elif i in (20, 21, 22, 23):
                self.bind[i] = self.bind[18 if i in (20, 22) else 19]

    def pose(self, source_rotations, root):
        rotations = source_rotations[MAP] @ self.bind
        joints = np.zeros((24, 3))
        joints[0] = np.asarray(root) + source_rotations[0] @ self.source_hip_center - rotations[0] @ self.target_hip_center
        for i in range(1, 24):
            joints[i] = joints[PARENTS[i]] + rotations[PARENTS[i]] @ self.offsets[i]
        return joints, rotations


def decode_rotations(feature, parents, m6d_to_rotmat):
    """LAFAN feature (267,) -> 22 global joint rotations in the MuJoCo world frame (heading frame of the frame)."""
    local = m6d_to_rotmat(torch.tensor(feature[135:].reshape(22, 6), dtype=torch.float64)).numpy()
    rotations = []
    for i, p in enumerate(parents):
        rotations.append(local[i] if p < 0 else rotations[p] @ local[i])
    return SOURCE_TO_WORLD @ np.array(rotations) @ SOURCE_TO_WORLD.T


def find_bind_reference(stats):
    """Pick a real near-T-pose LAFAN frame for twist calibration (BVH zero rotations are not a T-pose)."""
    with np.load(ROOT / 'data/LAFAN1/data.npz') as cache:
        normalized = cache['motion_flattened'][::10].copy()
    raw = normalized * stats['std'] + stats['avg']
    j = np.einsum('ij,fkj->fki', SOURCE_TO_WORLD, raw[:, 3:69].reshape(-1, 22, 3))
    side = j[:, 1] - j[:, 5]; side /= np.linalg.norm(side, axis=-1, keepdims=True)
    up = j[:, 12] - j[:, 0]; up -= side * np.sum(up * side, axis=-1, keepdims=True)
    up /= np.linalg.norm(up, axis=-1, keepdims=True)
    score = np.zeros(len(j))
    for a, b, sign in ((15, 16, 1), (16, 17, 1), (19, 20, -1), (20, 21, -1)):  # arms along the shoulder axis
        d = j[:, b] - j[:, a]; d /= np.linalg.norm(d, axis=-1, keepdims=True)
        score += np.sum((d - sign * side) ** 2, axis=-1)
    for a, b in ((1, 2), (2, 3), (5, 6), (6, 7)):  # legs straight down
        d = j[:, b] - j[:, a]; d /= np.linalg.norm(d, axis=-1, keepdims=True)
        score += np.sum((d + up) ** 2, axis=-1)
    k = int(np.argmin(score))
    return raw[k], j[k], k * 10, float(score[k])


# ---- Xbox -> joystick command ----------------------------------------------------------------------------------
class StickMapper:
    """World-fixed Xbox mapping for the joystick policy.

    Left stick = walking velocity in the ground plane (up = away from the camera as it was at reset, full tilt
    3 m/s), right stick = facing direction to hold. The policy takes body-frame (forward, right, clockwise yaw
    rate), so the world command is converted with the current heading. The actual world velocity (smoothed) is
    fed back with gain `gain`, so the policy's lag while turning does not drag the walking direction around with
    the heading. A 1-D policy (forward speed only) uses the left stick's up/down axis.
    """

    def __init__(self, gamepad, env, gain=.7):
        self.pad, self.env, self.gain = gamepad, env, gain
        self.reset()

    def reset(self):
        self.frame = None          # stick frame azimuth (rad), captured at the first read after reset
        self.facing_goal = None    # viewer-world yaw to hold
        self.actual = np.zeros(2)  # smoothed actual world velocity, viewer (x, y)
        self.goal_velocity = np.zeros(2)

    def body_yaw(self):
        return math.pi / 2 - float(self.env.root_facing[0, 0])

    def observe(self, velocity_xy):
        self.actual = .8 * self.actual + .2 * np.asarray(velocity_xy)

    def command(self, azimuth_deg):
        lx, ly, rx, ry = self.pad.sticks()
        if self.frame is None:
            self.frame = math.radians(azimuth_deg)
        by = self.body_yaw()
        if getattr(self.env, 'command_dims', 3) == 1:
            self.facing_goal = by
            forward = float(np.clip(3. * ly if ly >= 0 else ly, -1., 3.))
            self.goal_velocity = forward * np.array([math.cos(by), math.sin(by)])
            return [forward, 0., 0.]
        fwd_axis = np.array([math.cos(self.frame), math.sin(self.frame)])
        right_axis = np.array([math.sin(self.frame), -math.cos(self.frame)])
        world = 3. * (ly * fwd_axis + lx * right_axis)
        self.goal_velocity = world.copy()
        if np.linalg.norm(world) > 1e-3:  # feedback only while the stick is pushed
            world = world + self.gain * (world - self.actual)
            n = np.linalg.norm(world)
            if n > 3.:
                world *= 3. / n
        if self.facing_goal is None:
            self.facing_goal = by
        if math.hypot(rx, ry) > .5:
            d = ry * fwd_axis + rx * right_axis
            self.facing_goal = math.atan2(d[1], d[0])
        bf = np.array([math.cos(by), math.sin(by)]); br = np.array([math.sin(by), -math.cos(by)])
        forward = float(np.clip(world @ bf, -1., 3.))
        right = float(np.clip(world @ br, -1., 1.)) * min(1., max(0., (3. - forward) / 1.5))
        yaw = float(np.clip(2. * wrap_angle(self.facing_goal - by), -1.5, 1.5))
        return [forward, right, yaw]


# ---- scene markers -----------------------------------------------------------------------------------------------
class Markers:
    def __init__(self, mujoco, scene):
        self.mj, self.scn = mujoco, scene

    def clear(self):
        self.scn.ngeom = 0

    def geom(self, kind, size, pos, rgba, rot=np.eye(3)):
        if self.scn.ngeom >= self.scn.maxgeom:
            return None
        g = self.scn.geoms[self.scn.ngeom]; self.scn.ngeom += 1
        self.mj.mjv_initGeom(g, kind, np.array(size, dtype=np.float64), np.array(pos, dtype=np.float64),
                             np.asarray(rot, dtype=np.float64).flatten(), np.array(rgba, dtype=np.float32))
        return g

    def bar(self, base, vec, z, rgba):
        """Thin flat box on the ground from base along vec (viewer world xy)."""
        n = float(np.linalg.norm(vec))
        if n < 1e-3:
            return
        c, s = vec[0] / n, vec[1] / n
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
        self.geom(self.mj.mjtGeom.mjGEOM_BOX, (n / 2, .025, .005), base + np.array([vec[0] / 2, vec[1] / 2, z]), rgba, rot)

    def arrow(self, start, env_yaw, length, rgba):
        """Arrow along an env-plane yaw: (cos, sin) in env (x, z) is (cos, -sin) in viewer (x, y)."""
        end = np.array(start) + length * np.array([math.cos(env_yaw), -math.sin(env_yaw), 0.])
        g = self.geom(self.mj.mjtGeom.mjGEOM_ARROW, (.03, .03, .03), start, rgba)
        if g is not None:
            self.mj.mjv_connector(g, self.mj.mjtGeom.mjGEOM_ARROW, .035, np.array(start, dtype=np.float64), end)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--prior', type=Path, default=DEFAULT_PRIOR, help='A-MDM checkpoint (config.yaml next to it)')
    p.add_argument('--controller', type=Path, help='target / path / joystick policy.pth (args.json next to it)')
    p.add_argument('--xbox', action='store_true', help='joystick: drive the commands with an Xbox controller')
    p.add_argument('--command', type=float, nargs=3, default=[1., 0., 0.], metavar=('FORWARD', 'RIGHT', 'YAW'),
                   help='joystick without --xbox: fixed body-frame command (m/s, m/s, clockwise rad/s)')
    p.add_argument('--no_map', action='store_true', help='target/path: no map window (random targets / paths)')
    p.add_argument('--path_seconds', type=float, default=60., help='path: length of each path')
    p.add_argument('--body', choices=['smpl', 'capsule'], default=None,
                   help='smpl: fitted SMPL-H mesh; capsule: primitive person (default: smpl if available)')
    p.add_argument('--smpl_source', type=Path, default=SMPL_SOURCE, help='fitted SMPL-H npz for --body smpl')
    p.add_argument('--seed_clip', default='walk1_subject1', help='LAFAN clip the motion starts from')
    p.add_argument('--seed_frame', type=int, default=100)
    p.add_argument('--device', default='cuda:0')
    return p.parse_args()


def main():
    a = parse_args()
    if a.xbox and not a.controller:
        raise SystemExit('--xbox needs a joystick --controller')
    os.chdir(ROOT)  # upstream dataset paths are relative to the project root
    torch.set_num_threads(2)
    from amdm_interactive.core.model.amdm_model import AMDM
    from amdm_interactive.core.dataset.util.bvh import read_bvh_loco, get_parent_from_link
    from amdm_interactive.core.dataset.util.geo import m6d_to_rotmat
    import mujoco
    import mujoco.viewer

    # Prior.
    prior = a.prior.resolve()
    cfg = yaml.safe_load((prior.parent / 'config.yaml').read_text())
    with np.load(ROOT / 'data/LAFAN1/stats.npz') as d:
        stats = {k: d[k] for k in d.files}
    parents = get_parent_from_link(stats['links'])
    skeleton = types.SimpleNamespace(frame_dim=int(stats['frame_dim']), joint_parent=parents,
                                     joint_offset=stats['joint_offset'] / 100.)
    model = AMDM(cfg, skeleton, a.device).eval()
    model.load_state_dict(torch.load(prior, map_location=a.device))
    model.eval()
    mean, std = stats['avg'], stats['std']

    # Controller.
    task = env = policy = gamepad = sticks = None
    if a.controller:
        from amdm_interactive.core import load_lafan
        from amdm_interactive.core.policy.learning.ppo_model import PPOModel
        from amdm_interactive.envs import ENVS, XboxCommand
        manifest = json.loads((a.controller.parent / 'args.json').read_text())
        task = manifest['task']
        if a.xbox and task != 'joystick':
            raise SystemExit('--xbox needs a joystick policy')
        env_cfg = dict(manifest['env'], num_parallel=1, is_rendered=False)
        if task == 'path':
            env_cfg['max_timestep'] = int(a.path_seconds * 30)
        dataset = load_lafan(str(prior.parent / 'config.yaml'))
        env = ENVS[task](env_cfg, model, dataset, a.device)
        policy = PPOModel(manifest['agent'], env, a.device).eval()
        policy.load_state_dict(torch.load(a.controller, map_location=a.device, weights_only=False))
        if task == 'joystick':
            env.set_command(a.command)
        if a.xbox:
            gamepad = XboxCommand()
            sticks = StickMapper(gamepad, env)

    # Body and retargeting.
    frames, _ = read_bvh_loco(str(ROOT / 'data/LAFAN1' / f'{a.seed_clip}.bvh'), 'meter', 30, -90)
    seed = frames[a.seed_frame].copy()
    body_kind = a.body or ('smpl' if a.smpl_source.is_file() else 'capsule')
    if body_kind == 'smpl' and not a.smpl_source.is_file():
        raise SystemExit(f'No fitted SMPL template at {a.smpl_source}: run amdm_interactive.fit_smpl_shape '
                         '(see README.md) or use --body capsule')
    names = list(stats['joint_names'])
    retarget = None
    capsule = CapsuleBody(names)  # drawn as scene geoms, so it works in either scene
    bone_offsets = (SOURCE_TO_WORLD @ (stats['joint_offset'] / 100.).T).T  # LAFAN offsets, MuJoCo world axes
    if a.smpl_source.is_file():
        body = SMPLMujocoBody(source=a.smpl_source, mesh_cache=a.smpl_source.parent / 'mesh_cache',
                              visual='skin', collision=True)
        bind_feature, bind_positions, bind_index, bind_score = find_bind_reference(stats)
        retarget = SMPLRetarget(body.rest, (SOURCE_TO_WORLD @ (stats['joint_offset'] / 100.).T).T, parents,
                                decode_rotations(bind_feature, parents, m6d_to_rotmat), bind_positions)
        print(f'SMPL body available (bind pose from LAFAN frame {bind_index}, score {bind_score:.4f}); '
              f'starting with the {body_kind} body, C swaps', flush=True)
    else:
        body = capsule
        print('Capsule person body (no fitted SMPL template, see README.md)', flush=True)

    def set_body(kind):
        """Show the SMPL mesh or the capsule person (the SMPL scene stays loaded; its mesh is hidden)."""
        if retarget is not None:
            body.model.skin_rgba[:, 3] = 1.0 if kind == 'smpl' else 0.0
        return kind

    # Maps.
    bev = None
    if task == 'target' and not a.no_map:
        from amdm_interactive.bev_map import BEVMap
        bev = BEVMap()
        env.retarget_rate = 0.  # targets move only on clicks; reached targets still respawn at random
    if task == 'path' and not a.no_map:
        from amdm_interactive.bev_map import PathSketchMap
        from amdm_interactive import drawn_path
        bev = PathSketchMap(allow_facing=getattr(env, 'facing_command', 'free') == 'free')

    keys = queue.SimpleQueue()
    s = types.SimpleNamespace(x=None, feature=seed.copy(), xy=np.zeros(2), yaw=0., frame=0, status='Running',
                              paused=False, ground_truth=False, reached=0, hold=False,
                              velocity=np.zeros(2), yaw_rate=0.)

    def reset():
        torch.manual_seed(2026); torch.cuda.manual_seed_all(2026)
        s.x = torch.tensor((seed - mean) / std, device=a.device, dtype=torch.float32)[None]
        s.feature, s.yaw, s.frame, s.status, s.reached = seed.copy(), 0., 0, 'Running', 0
        s.xy[:] = 0
        if env is None:
            return
        torch.manual_seed(int(time.time()))  # fresh random targets / paths each reset
        env.reset()
        env.history[:, :1] = s.x[:, None, :]
        if sticks is not None:
            sticks.reset()
        if task == 'path' and bev is not None:
            drawn_path.random_path(env)  # start on a random training-style path; draw to replace it
            s.hold = False
        if task == 'target':
            env.reset_target()
        if bev is not None:
            bev.trail.clear()

    def step():
        """Advance one 30 Hz frame: controller step, unconditional prior step, or ground-truth playback."""
        with torch.no_grad():
            if policy is not None and not s.ground_truth:
                if sticks is not None:
                    env.set_command(sticks.command(viewer.cam.azimuth))
                obs = torch.cat(env.get_observation_components(), dim=1)
                before = env.target.clone() if task == 'target' else None
                prev_xz, prev_facing = env.root_xz[0].clone(), env.root_facing[0, 0].clone()
                env.step(policy.actor(obs))
                v = ((env.root_xz[0] - prev_xz) * 30).tolist()
                s.velocity = np.array([v[0], -v[1]])  # env (x, z) -> viewer (x, y)
                s.yaw_rate = -float(wrap_angle(env.root_facing[0, 0] - prev_facing)) * 30
                if sticks is not None:
                    sticks.observe(s.velocity)
                if task == 'target' and not torch.equal(before, env.target):
                    s.reached += 1
                s.x = env.history[:, 0]
                s.feature = s.x[0].cpu().numpy() * std + mean
            elif s.ground_truth:
                s.feature = frames[(a.seed_frame + s.frame) % len(frames)].copy()
            else:
                s.x = model.eval_step(s.x, align_rpr=False)
                s.feature = s.x[0].cpu().numpy() * std + mean
        if not np.isfinite(s.feature).all() or (not s.ground_truth and float(s.x.abs().max()) > 1000):
            s.status = 'Diverged: R to reset'
            return
        c, si = math.cos(s.yaw), math.sin(s.yaw)
        s.xy += np.array([[c, -si], [si, c]]) @ np.array([s.feature[0], -s.feature[1]])
        s.yaw -= float(s.feature[2])

    def show_body():
        c, si = math.cos(s.yaw), math.sin(s.yaw)
        heading = np.array([[c, -si, 0], [si, c, 0], [0, 0, 1.]])
        source = heading @ decode_rotations(s.feature, parents, m6d_to_rotmat)
        # Capsule person: forward kinematics from the rotations (as the SMPL mesh), not the position channels: the
        # prior's hip planar channels have unit normalization std and carry ~4x the frame-to-frame jitter.
        joints = np.zeros((22, 3))
        joints[0] = np.r_[s.xy, s.feature[4]]
        for i, p in enumerate(parents):
            if p >= 0:
                joints[i] = joints[p] + source[p] @ bone_offsets[i]
        if not np.isfinite(joints).all() or np.any(np.linalg.det(source) < .5):
            s.status = 'Invalid rotations: R to reset'
            return
        capsule.set_pose(joints, source)
        if retarget is not None:  # keep the SMPL body (and its light / floor tracking) posed in both modes
            smpl_joints, smpl_rotations = retarget.pose(source, np.r_[s.xy, s.feature[4]])
            if not np.isfinite(smpl_joints).all() or np.any(np.linalg.det(smpl_rotations) < .5):
                s.status = 'Invalid rotations: R to reset'
                return
            body.set_pose(smpl_joints, smpl_rotations)
        viewer.cam.lookat[:] = joints[0] - [0, 0, .1]

    def target_overlay(markers):
        if bev is not None:
            click = bev.update(s.xy, math.pi / 2 - float(env.root_facing[0, 0]), viewer.cam.azimuth,
                               env.target[0].tolist(), env.reach_radius)
            if click is not None:  # viewer world (x, y) -> env (x, z)
                env.reset_target(location=(click[0], -click[1]))
        tx, tz = env.target[0].tolist()
        for size, z, rgba in (((.4, .4, .01), .005, (1, .2, .2, .35)), ((.05, .05, .8), .8, (1, .2, .2, 1))):
            markers.geom(mujoco.mjtGeom.mjGEOM_CYLINDER, size, (tx, -tz, z), rgba)
        return f'\nTarget {math.hypot(tx - s.xy[0], -tz - s.xy[1]):.2f} m away, reached {s.reached}'

    def joystick_overlay(markers):
        # Blue = velocity (0.5 m per m/s), yellow = facing; transparent = command, opaque = actual.
        forward, right, yaw_cmd = env.commands[0].tolist()
        by = math.pi / 2 - float(env.root_facing[0, 0])
        bf = np.array([math.cos(by), math.sin(by)]); br = np.array([math.sin(by), -math.cos(by)])
        command_v = sticks.goal_velocity if sticks is not None else forward * bf + right * br
        goal = sticks.facing_goal if sticks is not None and sticks.facing_goal is not None else by
        base = np.array([s.xy[0], s.xy[1], 0.])
        markers.bar(base, .5 * command_v, .01, (.15, .45, 1, .35))
        markers.bar(base, .5 * s.velocity, .02, (.15, .45, 1, 1))
        markers.bar(base, .8 * np.array([math.cos(goal), math.sin(goal)]), .03, (1, .85, .1, .35))
        markers.bar(base, .8 * bf, .04, (1, .85, .1, 1))
        return (f'\nCommand fwd {forward:+.2f} right {right:+.2f} m/s yaw {yaw_cmd:+.2f} (blue, faint)'
                f'\nActual  fwd {s.velocity @ bf:+.2f} right {s.velocity @ br:+.2f} m/s yaw {s.yaw_rate:+.2f} (blue, solid)'
                f'\nFacing error {math.degrees(abs(wrap_angle(goal - by))):.0f} deg (yellow: faint goal, solid body)'
                f'\n{"Xbox: left stick velocity, right stick facing" if gamepad else "Fixed --command"}')

    def path_overlay(markers):
        if bev is not None:
            sketch = bev.update(s.xy, math.pi / 2 - float(env.root_facing[0, 0]), viewer.cam.azimuth,
                                env.path[0].cpu().numpy() * [1, -1], env.path_vel[0].norm(dim=-1).cpu().numpy(),
                                int(env.path_t[0]))
            kind = sketch[0] if sketch is not None else None
            stroke, v0, off0 = None, 0., 0.
            if kind == 'path':  # viewer world (x, y) -> env (x, z)
                stroke = [(q[0], -q[1]) for q in sketch[1]]
            elif kind == 'retime':  # rest of the current path at the new speed / facing
                stroke = drawn_path.remaining(env)
                v0, off0 = drawn_path.current_motion(env)
            elif kind == 'random':
                drawn_path.random_path(env, continue_motion=True)
            elif kind == 'stop':
                drawn_path.stand_still(env)
            s.hold = kind == 'stop' or (s.hold and kind not in ('path', 'random'))
            if stroke is not None and len(stroke) > 0:
                # Map facing offsets are viewer counter-clockwise; env yaw runs the other way.
                drawn_path.install(env, *drawn_path.build(
                    env.root_xz[0].cpu().numpy(), float(env.body_yaw()[0]), stroke, bev.speed, -bev.facing[0],
                    env.path_len, start_speed=v0, start_offset=off0))
            if not s.hold and drawn_path.finished(env):  # keep going: chain a new random path from here
                drawn_path.random_path(env, continue_motion=True)
        t, n = int(env.path_t[0]), env.path_len
        path_xy = env.path[0].cpu().numpy() * [1, -1]
        speeds = env.path_vel[0].norm(dim=-1).cpu().numpy()
        cmd_face, body_face = float(env.path_facing[0, t]), float(env.body_yaw()[0])
        for k in range(max(0, t - 90), min(n, t + 150), 3):  # path dots coloured by speed, past ones faint
            v = min(speeds[k] / 4., 1.)
            markers.geom(mujoco.mjtGeom.mjGEOM_SPHERE, (.035, 0, 0), (*path_xy[k], .02), (v, .3, 1 - v, .9 if k >= t else .25))
        for dk in env.lookahead.tolist():  # the points the policy observes
            k = min(n - 1, t + dk)
            markers.geom(mujoco.mjtGeom.mjGEOM_CYLINDER, (.08, .08, .01), (*path_xy[k], .01), (1, .85, .1, .9))
        markers.geom(mujoco.mjtGeom.mjGEOM_CYLINDER, (.25, .25, .01), (*path_xy[t], .005), (1, .2, .2, .45))
        markers.arrow((*path_xy[t], .05), cmd_face, .7, (1, .2, .2, 1))
        markers.arrow((s.xy[0], s.xy[1], .08), body_face, .6, (.2, 1, .3, 1))
        return (f'\nPath {t / 30:.1f}/{(n - 1) / 30:.0f} s, off-path {float(env.track_error[0]):.2f} m'
                f'\nSpeed cmd {speeds[t]:.2f} / actual {float(np.linalg.norm(s.velocity)):.2f} m/s'
                f'\nFacing error {math.degrees(abs(wrap_angle(body_face - cmd_face))):.0f} deg (red = command, green = body)')

    overlays = {'target': target_overlay, 'joystick': joystick_overlay, 'path': path_overlay}
    print('Viewer keys: R reset | Space pause | C SMPL mesh / capsule person | E EMA/current weights | G ground-truth clip', flush=True)
    body_kind = set_body(body_kind)
    with mujoco.viewer.launch_passive(body.model, body.data, key_callback=keys.put) as viewer:
        viewer.cam.distance, viewer.cam.azimuth, viewer.cam.elevation = 3., 135, -15
        markers = Markers(mujoco, viewer.user_scn)
        reset()
        while viewer.is_running():
            tick = time.monotonic()
            while not keys.empty():
                code = keys.get()
                if code == ord('R'):
                    reset()
                elif code == 32:
                    s.paused = not s.paused
                elif code == ord('C') and retarget is not None:
                    with viewer.lock():
                        body_kind = set_body('capsule' if body_kind == 'smpl' else 'smpl')
                elif code == ord('E'):
                    model.use_ema = not model.use_ema; reset()
                elif code == ord('G'):
                    s.ground_truth = not s.ground_truth; reset()
            if not s.paused and s.status == 'Running' and s.frame > 0:
                step()
            if s.status == 'Running':
                show_body()
            extra = ''
            with viewer.lock():
                markers.clear()
                if body_kind == 'capsule' and s.status == 'Running':
                    capsule.draw(markers)
                if task is not None:
                    extra = overlays[task](markers)
            mode = 'ground-truth clip' if s.ground_truth else (f'{task} controller' if task else 'prior (unconditional)')
            viewer.set_texts((None, None, 'Prior\nWeights\nMode\nFrame\nStatus',
                              f'{prior.name}\n{"EMA" if model.use_ema else "current"}\n{mode}\n{s.frame}\n{s.status}{extra}'))
            viewer.sync()
            if not s.paused and s.status == 'Running':
                s.frame += 1
            time.sleep(max(0., 1 / 30 - (time.monotonic() - tick)))


if __name__ == '__main__':
    main()
