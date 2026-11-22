"""Train a target / path / joystick PPO controller on a frozen A-MDM prior.

Run from the project root (interactive_control/ in the AMDM repo), e.g.
    python -m amdm_interactive.train --task target --run target \
        --checkpoint output/base/amdm_lafan1_t16/model_param.pth

The prior's config.yaml must sit next to the checkpoint. Outputs go to output/interactive/<run>/:
policy.pth (latest weights), recovery.pth (weights + optimizer, saved after every update), log.jsonl (one row
per update) and args.json (everything needed to rebuild the env and policy, read by interactive.viewer).
Re-running the same command resumes from recovery.pth unless --fresh is given.
See README.md for the settings used for the released controllers.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--task', choices=['target', 'path', 'joystick'], required=True)
    p.add_argument('--checkpoint', type=Path, required=True, help='frozen A-MDM prior (config.yaml next to it)')
    p.add_argument('--run', default='', help='output/interactive/<run> (default: the task name)')
    p.add_argument('--fresh', action='store_true', help='ignore an existing recovery.pth')
    p.add_argument('--device', default='cuda:0')
    g = p.add_argument_group('PPO')
    g.add_argument('--num_envs', type=int, default=32)
    g.add_argument('--updates', type=int, default=4000, help='total PPO updates (including resumed ones)')
    g.add_argument('--minibatch', type=int, default=200)
    g.add_argument('--ppo_epochs', type=int, default=20)
    g.add_argument('--final_lr', type=float, default=5e-6, help='lr floor of the x0.99/update decay')
    g = p.add_argument_group('all tasks')
    g.add_argument('--clip_scale', type=float, default=2.5, help='clamp on x after each action injection')
    g.add_argument('--root_action_mask', action='store_true',
                   help='zero the root velocity/yaw channels of the correction slots (steer through the pose)')
    g.add_argument('--lying_weight', type=float, default=0., help='penalty for lying down (head below 1 m)')
    g.add_argument('--max_timestep', type=int, default=None, help='episode length in frames (path default 300)')
    g = p.add_argument_group('target task')
    g.add_argument('--facing_weight', type=float, default=0.1)
    g.add_argument('--facing_mode', choices=['cos', 'forward_vel'], default='forward_vel')
    g.add_argument('--backward_weight', type=float, default=1.0, help='penalty per m/s of backward root speed')
    g.add_argument('--reach_radius', type=float, default=0.75, help='distance (m) that counts as reached')
    g.add_argument('--retarget_rate', type=float, default=0.15, help='random target moves per second before reaching')
    g.add_argument('--progress_weight', type=float, default=1.0, help='weight on approach speed (m/s)')
    g.add_argument('--progress_cap', type=float, default=1.5, help='clip approach speed (m/s) in the progress term')
    g.add_argument('--distance_weight', type=float, default=0.1, help='weight on the dense term exp(-d/2) (upstream 2)')
    g.add_argument('--reach_bonus', type=float, default=20., help='reward on the step a target is reached (upstream 5)')
    g = p.add_argument_group('path task')
    g.add_argument('--facing_command', choices=['free', 'forward'], default='free',
                   help='facing offsets from the path tangent, or always face along the path')
    g.add_argument('--speed_max', type=float, default=4.0, help='fastest commanded waypoint speed (m/s)')
    g.add_argument('--fail_distance', type=float, default=2.0, help='terminate when this far from the waypoint (m)')
    g = p.add_argument_group('joystick task')
    g.add_argument('--command_dims', type=int, choices=[1, 3], default=3,
                   help='3 = forward/sideways/yaw rate, 1 = forward speed only')
    return p.parse_args()


def env_config(a, out):
    name = 'target' if a.task == 'joystick' else a.task
    cfg = yaml.safe_load((ROOT / f'configs/envs/{name}.yaml').read_text())
    # The upstream presets were written for T=32 priors; these step indices match a T=16 prior.
    cfg.update(num_parallel=a.num_envs, is_rendered=False, int_output_dir=str(out.relative_to(ROOT) / 'previews'),
               action_step=list(range(14, 1, -1)), action_rgr_step=[4, 3, 2], clip_scale=a.clip_scale,
               root_action_mask=a.root_action_mask, lying_weight=a.lying_weight)
    if a.task == 'target':
        cfg.update(facing_weight=a.facing_weight, facing_mode=a.facing_mode, backward_weight=a.backward_weight,
                   reach_radius=a.reach_radius, retarget_rate=a.retarget_rate, progress_weight=a.progress_weight,
                   progress_cap=a.progress_cap, distance_weight=a.distance_weight, reach_bonus=a.reach_bonus)
    elif a.task == 'path':
        cfg.update(speed_max=a.speed_max, fail_distance=a.fail_distance, facing_command=a.facing_command,
                   max_timestep=300)
    else:
        cfg.update(command_dims=a.command_dims)
    if a.max_timestep is not None:
        cfg['max_timestep'] = a.max_timestep
    return cfg


def main():
    a = parse_args()
    os.chdir(ROOT)  # upstream dataset paths (./data/...) are relative to the project root
    from amdm_interactive.core import load_lafan, build_amdm
    from amdm_interactive.core.policy.learning.ppo_model import PPOModel
    from amdm_interactive.core.policy.learning.ppo_agent import PPOAgent
    from amdm_interactive.envs import ENVS

    out = ROOT / 'output/interactive' / (a.run or a.task)
    (out / 'previews').mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    torch.manual_seed(122)
    np.random.seed(122)

    checkpoint = a.checkpoint.absolute()
    config_path = str(checkpoint.parent / 'config.yaml')
    dataset = load_lafan(config_path)
    model = build_amdm(config_path, dataset, a.device)
    model.load_state_dict(torch.load(checkpoint, map_location=a.device, weights_only=False))
    model.eval().requires_grad_(False)

    cfg = env_config(a, out)
    if a.num_envs * cfg['max_timestep'] % a.minibatch:
        raise ValueError('--minibatch must divide num_envs * max_timestep')
    env = ENVS[a.task](cfg, model, dataset, a.device)
    agent_cfg = yaml.safe_load((ROOT / 'configs/agents/ppo.yaml').read_text())
    agent_cfg.update(mini_batch_size=a.minibatch, ppo_epoch=a.ppo_epochs, final_lr=a.final_lr)
    agent = PPOAgent(agent_cfg, PPOModel(agent_cfg, env, a.device), env, a.device)
    agent.num_updates = a.updates

    prior = os.path.relpath(checkpoint, ROOT)
    manifest = dict(checkpoint=prior, task=a.task, updates=a.updates, env=cfg, agent=agent_cfg, frozen_prior=True)
    (out / 'args.json').write_text(json.dumps(manifest, indent=2))

    completed = 0
    if not a.fresh and (out / 'recovery.pth').exists():
        state = torch.load(out / 'recovery.pth', map_location=a.device, weights_only=False)
        agent.actor_critic.load_state_dict(state['policy'])
        agent.optimizer.load_state_dict(state['optimizer'])
        completed = int(state['update']) + 1
        agent.num_updates = max(0, a.updates - completed)
        # Continue the lr decay instead of restarting at the initial lr: jumping back up from the floor
        # preceded NaN policy blow-ups a few dozen updates after a resume.
        agent.lr = max(agent.final_lr, agent.lr * 0.99 ** completed)
        print(f'Resuming after {completed} PPO updates (lr {agent.lr:.2e})', flush=True)

    agent.logger.print_log = lambda data: print(
        json.dumps({k: v.item() if torch.is_tensor(v) else v for k, v in data.items()}), flush=True)
    wandb_log = agent.logger.log_epoch

    def log(data, step=None):
        """Per-update hook: log.jsonl row, recovery.pth, then the upstream wandb logger."""
        data = dict(data, update=int(data['update']) + completed)
        row = {k: v.item() if torch.is_tensor(v) else v for k, v in data.items()}
        if a.task == 'target' and env.reach_steps:  # targets reached per env per minute over this rollout
            row['reaches_per_min'] = env.reaches / env.num_parallel / (env.reach_steps / env.data_fps / 60)
            env.reaches = env.reach_steps = 0
        if not all(np.isfinite(v) for v in row.values()):
            raise RuntimeError(f'Nonfinite PPO metrics: {row}')
        with (out / 'log.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n')
        temporary = out / 'recovery.tmp'
        torch.save(dict(update=row['update'], policy=agent.actor_critic.state_dict(),
                        optimizer=agent.optimizer.state_dict(), manifest=manifest), temporary)
        os.replace(temporary, out / 'recovery.pth')
        print(f"{a.task}: completed PPO update {row['update'] + 1}/{a.updates}", flush=True)
        wandb_log(data, step=step)

    agent.logger.log_epoch = log
    print(f'Starting {a.task} PPO; prior={prior}; envs={a.num_envs}; updates={a.updates}', flush=True)
    agent.train_controller(str(out / 'policy.pth'), str(out / 'previews'))
    print(f'Finished {a.task} PPO', flush=True)


if __name__ == '__main__':
    main()
