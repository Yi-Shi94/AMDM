"""Headless target-reaching evaluation: success rate and motion quality, with LAFAN mocap as reference.

    python -m amdm_interactive.evaluate_target output/interactive/target/policy.pth [more policies ...]

Every policy sees the same seeds and targets (random target moves off). Per policy, one JSON line with:
  reaches_per_min  targets reached per character per minute
  speed_mean/p95   root planar speed (m/s)
  foot_slide       planar foot speed while the foot is near its lowest height (m/s; compare policies, not absolute)
  jerk             mean |third difference| of joint positions (m/s^3)
  lying            fraction of frames with the head below 1 m
LAFAN feature layout: root (3) | joint positions (22 x 3, heading frame, y up) | joint velocities (22 x 3,
per frame) | 6D rotations.
"""
import argparse
import json
import os
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
FPS, LOW = 30, .08
FEET = ('LeftFoot', 'LeftToe', 'RightFoot', 'RightToe')


def quality(raw, names):
    """raw (T, N, 267) denormalized frames -> motion-quality metrics."""
    j = len(names)
    pos = raw[..., 3:3 + 3 * j].reshape(*raw.shape[:2], j, 3)
    vel = raw[..., 3 + 3 * j:3 + 6 * j].reshape(*raw.shape[:2], j, 3) * FPS
    feet = [names.index(n) for n in FEET]
    foot_h, foot_v = pos[..., feet, 1], vel[..., feet, :][..., [0, 2]].norm(dim=-1)
    low = foot_h < (foot_h.amin(dim=(0, 2), keepdim=True) + LOW)
    speed = raw[..., :2].norm(dim=-1) * FPS
    return dict(speed_mean=float(speed.mean()), speed_p95=float(speed.flatten().quantile(.95)),
                foot_slide=float((foot_v * low).sum() / low.sum().clamp_min(1)),
                jerk=float((vel[2:] - 2 * vel[1:-1] + vel[:-2]).norm(dim=-1).mean() * FPS * FPS),
                lying=float((pos[..., names.index('Head'), 1] < 1.).float().mean()))


@torch.no_grad()
def evaluate(policy_path, model, dataset, envs, steps, device):
    from amdm_interactive.core.policy.learning.ppo_model import PPOModel
    from amdm_interactive.envs import FacingTargetEnv
    manifest = json.loads((policy_path.parent / 'args.json').read_text())
    cfg = dict(manifest['env'], num_parallel=envs, is_rendered=False, max_timestep=steps + 10, retarget_rate=0.)
    env = FacingTargetEnv(cfg, model, dataset, device)
    policy = PPOModel(manifest['agent'], env, device).eval()
    policy.load_state_dict(torch.load(policy_path, map_location=device, weights_only=False))
    torch.manual_seed(2026); torch.cuda.manual_seed_all(2026)
    obs = env.reset()
    env.reaches = env.reach_steps = 0
    frames = []
    for _ in range(steps):
        obs, _, _, _ = env.step(policy.actor(obs))
        frames.append(dataset.denorm_data(env.history[:, 0], device=device))
    out = quality(torch.stack(frames), list(dataset.joint_names))
    out['reaches_per_min'] = env.reaches / envs / (steps / FPS / 60)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('policies', nargs='+', type=Path)
    p.add_argument('--prior', type=Path, default=ROOT / 'output/base/amdm_lafan1_t16/model_param.pth')
    p.add_argument('--envs', type=int, default=64)
    p.add_argument('--seconds', type=float, default=30.)
    p.add_argument('--device', default='cuda:0')
    a = p.parse_args()
    policies = [q.resolve() for q in a.policies]
    prior = a.prior.resolve()
    os.chdir(ROOT)
    from amdm_interactive.core import load_lafan, build_amdm
    config_path = str(prior.parent / 'config.yaml')
    dataset = load_lafan(config_path)
    model = build_amdm(config_path, dataset, a.device)
    model.load_state_dict(torch.load(prior, map_location=a.device, weights_only=False))
    model.eval().requires_grad_(False)
    mocap = torch.as_tensor(dataset.motion_flattened[:60000], device=a.device, dtype=torch.float32)
    ref = quality(dataset.denorm_data(mocap, device=a.device)[:, None], list(dataset.joint_names))
    print(json.dumps(dict(policy='LAFAN mocap', **ref)), flush=True)
    for policy in policies:
        print(json.dumps(dict(policy=str(policy), **evaluate(policy, model, dataset, a.envs,
                                                               int(a.seconds * FPS), a.device))), flush=True)


if __name__ == '__main__':
    main()
