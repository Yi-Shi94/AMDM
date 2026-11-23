# A-MDM Interactive Control

PPO controllers that steer a frozen, T=16 [A-MDM](https://github.com/Yi-Shi94/AMDM) motion prior trained on LAFAN1,
plus a real-time MuJoCo viewer (SMPL mesh or capsule person) with Xbox input, clickable targets and hand-drawn paths.
Self-contained: the parts of A-MDM it needs are vendored in `amdm_interactive/core/`, so this folder runs on its own
(run every command from inside `interactive_control/`).


| Task | What the policy is asked to do | Observation (besides the 267-D frame) |
|---|---|---|
| **target** | walk to a target that can move at any time; a new one appears as soon as it is reached | target in the heading frame |
| **path** | follow a 30 Hz waypoint path whose speed varies from standstill to 4 m/s, while holding a separate facing direction | 7 path points over the next 2.5 s, commanded velocity, commanded facing |
| **path (forward)** | same paths, always facing along the path | same |
| **joystick** | track a body-frame command: forward / sideways speed and yaw rate | the command |
| **joystick (1-D)** | track a forward-speed command only | the command |

The policy acts on the diffusion sampler ("full" action mode): it shifts the initial noise and adds a correction
after denoising steps 14..2, and `x` is clamped to `--clip_scale` (2.5) after each injection.

## Setup

Tested with Python 3.10, PyTorch 1.13.1 (CUDA 11.7), MuJoCo 3.10 and pygame 2.6, on Linux.

```bash
pip install -r requirements.txt
```

### Download data and checkpoints

```bash
bash scripts/download.sh            # prior + controllers + LAFAN1 clips (~250 MB), checksummed, unpacked in place
bash scripts/download.sh --no-lafan # skip LAFAN1 if you already have it (put the .bvh files in data/LAFAN1/)
```

Or download the files from the [interactive-v1.0 release](https://github.com/Yi-Shi94/AMDM/releases/tag/interactive-v1.0) and
unzip each into this folder (`interactive_control/`):

| Archive | Contents | Unpacks to |
|---|---|---|
| `amdm_lafan1_t16.zip` (108 MB) | T=16 LAFAN1 prior: `model_param.pth`, `config.yaml` | `output/base/amdm_lafan1_t16/` |
| `amdm_interactive_controllers.zip` (25 MB) | the five controllers: `policy.pth` + `args.json` each | `output/interactive/{target,path,path_forward,joystick,joystick_1d}/` |
| `lafan1_bvh.zip` (120 MB) | the 60 LAFAN1 BVH clips used (CC BY-NC-ND 4.0, Ubisoft La Forge) | `data/LAFAN1/` |

LAFAN1 can also be downloaded from [ubisoft-laforge-animation-dataset](https://github.com/ubisoft/ubisoft-laforge-animation-dataset)
(the `obstacles*` clips are not used). The first run parses the clips into `data/LAFAN1/data.npz` (a few minutes);
the committed `data/LAFAN1/stats.npz` holds the normalization the prior was trained with.

The resulting layout:

```
data/LAFAN1/            stats.npz (committed), *.bvh, data.npz (built on first run)
output/base/amdm_lafan1_t16/   model_param.pth, config.yaml
output/interactive/<name>/     policy.pth, args.json   (target, path, path_forward, joystick, joystick_1d)
body_models/smpl_lafan_fitted/ SMPL_LAFAN_FITTED.npz   (optional, see below)
```

### Viewer body: SMPL mesh or capsule person

`--body capsule` draws the primitive capsule person used for the A-MDM people in the GenerativeWBC dodge task
(torso, head and limb capsules, hand spheres, foot boxes); it needs nothing extra. `--body smpl` shows an SMPL-H
mesh fitted to the LAFAN skeleton (the default once the fitted file exists; **C** in the viewer swaps between the two). The SMPL-H model cannot be redistributed: register at
[mano.is.tue.mpg.de](https://mano.is.tue.mpg.de), download the *Extended SMPL+H model*, and fit it once:

```bash
python -m amdm_interactive.fit_smpl_shape --source body_models/smplh/neutral/model.npz
# -> body_models/smpl_lafan_fitted/SMPL_LAFAN_FITTED.npz (10 betas + one scale; ~3 cm mean bone-length error)
```


## Viewer

```bash
python -m amdm_interactive.viewer                                             # prior alone
python -m amdm_interactive.viewer --controller output/interactive/target/policy.pth
python -m amdm_interactive.viewer --controller output/interactive/path/policy.pth
python -m amdm_interactive.viewer --controller output/interactive/joystick/policy.pth
```

The SMPL mesh is the default body when the fitted template exists; **C** swaps to the capsule person and back (`--body capsule` starts with it). MuJoCo window: **R** reset, **Space** pause, **C** SMPL mesh / capsule person, **E** EMA / current prior weights,
**G** play the ground-truth seed clip.

**Target**: a bird's-eye map opens next to the viewer. Left-click places the target; once the character is within
the reach radius (0.75 m) a new target spawns at random. Mouse wheel zooms.

**Path**: the character starts on a random training-style path (a new one on R) and never stops on its own: when
a path runs out, a new random path continues from the current speed and heading. Random paths vary speed and
turning but hold the map's facing setting (forward by default) unless **H** turns on random facing changes. Draw on the map to
replace the path (click the map window first so it receives keys).

| Input | Effect |
|---|---|
| left-drag | draw a path; on release the character walks to its start and follows it, then continues on a random path |
| 1-5 | speed 0.5 / 1 / 1.5 / 2.5 / 3.5 m/s |
| Up / Down | speed +/- 0.25 m/s (0.25-4) |
| Left / Right | turn the facing offset from the walking direction by 15° |
| F | facing preset: forward / left / backward / right of the walking direction |
| G | random path from the training generator (varying speed and turning) |
| H | random facing changes on random paths: on / off (off by default) |
| right-click | stop here (holds until you draw or press G) |

Speed and facing changes re-time the path being followed, continuing from the current speed. Strokes are smoothed
and timed with the training limits (2.5 m/s² acceleration, 3 m/s² lateral acceleration). As in training, a sideways
or backward facing fades to forward between 1.5 and 3 m/s. `--no_map` plays random 60 s training paths instead.

**Joystick**: an Xbox-compatible pad is used when connected (also when plugged in later); otherwise random
commands play: every 3-6 s stand, or walk / jog / run (1, 1.8, 3 m/s) in a random direction, facing along it,
keeping the current facing or facing elsewhere. **X** switches between the pad and random commands. On the pad the
left stick sets walking velocity (full tilt 3 m/s forward, 1 m/s sideways or backward of the facing) and the right stick (pushed past halfway) sets the facing direction, both fixed to
the ground: "up" is away from the camera as it was at the last reset (or switch). The viewer converts this to the
policy's body-frame command and feeds back the measured world velocity, so the direction holds while the body
turns. The 1-D policy uses the left stick's up/down only. Ground bars: blue = velocity, yellow = facing; faint =
command, solid = actual. `--command FWD RIGHT YAW` plays a fixed command instead.

## Training

```bash
python -m amdm_interactive.train --task target --run target \
    --checkpoint output/base/amdm_lafan1_t16/model_param.pth --root_action_mask --lying_weight 2
```

Outputs go to `output/interactive/<run>/`: `policy.pth`, `recovery.pth` (weights + optimizer after every update;
re-running the same command resumes), `log.jsonl` and `args.json` (read by the viewer). W&B logging follows
`WANDB_MODE` (e.g. `WANDB_MODE=offline`). `scripts/train_slurm.sbatch` chains 12 h SLURM jobs on one run.

Settings of the released controllers (all: 20 PPO epochs, lr 2e-5 decaying x0.99 per update to 5e-6, fixed action
std 0.5, clamp 2.5):

| Controller | Task flags | Envs / minibatch | Updates |
|---|---|---|---|
| target | `--root_action_mask --lying_weight 2` (defaults: reach 0.75 m, progress capped at 1.5 m/s, reach bonus 20, closeness 0.1, facing 0.1, backward penalty 1, random target moves 0.15/s) | 32 / 200 | 18.9k |
| path | `--lying_weight 2` | 512 / 1024 | 4.6k |
| path_forward | `--lying_weight 2 --facing_command forward` | 512 / 1024 | 4.1k |
| joystick | `--lying_weight 1` | 512 / 1024 | 4.8k |
| joystick_1d | `--lying_weight 1 --command_dims 1` | 512 / 1024 | 4.2k |

The released controllers were trained in stages, and the flags above are the final stage. Path and joystick started
with clamp 3 and were fine-tuned at 2.5. The target policy started with clamp 3 and the upstream reward plus a
facing term (weight 0.5, then 0.2). It then switched to the progress and reach-bonus reward. The reason: with the
upstream dense closeness reward and a respawn on reach, orbiting just outside the reach radius pays more than
reaching. The progress term is capped because uncapped approach speed made the policy sprint and lunge; the
released target policy was fine-tuned with the cap from update 10.5k.

### Rewards

- **target**: `reach_bonus` on the step a target is reached, plus `progress_weight * min(approach speed, progress_cap)`, `distance_weight * exp(-d/2)`, `facing_weight * clamp(v_forward, 0, 1.5) * cos(angle to target)` and `-backward_weight * backward speed`.
- **path**: `2 exp(-(d/0.5)²) + exp(-|v - v_cmd|²/0.36) + exp(-(yaw error/0.5)²)`, where `d` is the distance to the current waypoint. The episode ends when `d` exceeds 2 m.
- **joystick**: `0.7 exp(-|v - v_cmd|²/0.5) + 0.3 exp(-(yaw rate error)²/0.5)`.
- **lying penalty** (all tasks): `-lying_weight * clamp((1 - head height)/0.6, 0, 1)`. There is no penalty with the head above 1 m (standing is 1.4-1.6 m, a crouch about 1 m) and the full penalty at 0.4 m.
- `--root_action_mask` zeroes the root velocity and yaw channels of the correction slots, so the policy must steer through the pose rather than push the root directly.

## Evaluation

```bash
python -m amdm_interactive.evaluate_target output/interactive/target/policy.pth
```

The evaluation reports targets reached per minute and motion quality: speed, foot sliding, jerk, and how often the head is below 1 m. It uses fixed seeds, and LAFAN mocap is measured the same way as a reference.

## Files

All under `amdm_interactive/`:

| File | |
|---|---|
| `envs/target.py`, `envs/path.py`, `envs/joystick.py` | the three tasks (subclasses of the A-MDM `TargetEnv`) |
| `train.py` | PPO training with resume |
| `viewer.py` | MuJoCo SMPL viewer, Xbox mapping, task overlays |
| `bev_map.py`, `drawn_path.py` | bird's-eye maps; stroke -> timed path with speed / facing limits |
| `smpl_body.py`, `fit_smpl_shape.py` | MuJoCo SMPL skin + collision proxies; SMPL-H shape fit to LAFAN |
| `capsule_body.py` | capsule person (GenerativeWBC dodge-task body) |
| `evaluate_target.py` | headless target evaluation |
| `core/` | vendored A-MDM subset: network + sampler, LAFAN loader, base/target env, PPO (BSD-3, see `core/LICENSE`) |

## Acknowledgements

Built on [A-MDM](https://github.com/Yi-Shi94/AMDM) (Shi et al., *Interactive Character Control with Auto-Regressive
Motion Diffusion Models*, ACM TOG 2024), whose RL modules build on [MotionVAE](https://github.com/electronicarts/character-motion-vaes).
LAFAN1 is by Ubisoft La Forge (CC BY-NC-ND 4.0). The capsule person's shapes follow MimicKit's DeepMimic humanoid.
