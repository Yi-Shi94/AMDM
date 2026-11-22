"""Minimal vendored subset of A-MDM (https://github.com/Yi-Shi94/AMDM, BSD-3-Clause, see LICENSE here).

Only what the controllers need: the A-MDM network and sampler (model/), the LAFAN1 loader and BVH / rotation
utilities (dataset/), the base and target environments (policy/envs/) and PPO (policy/learning/). Changes from
upstream: imports point at this package; the PyBullet renderer and plotting are not included; LAFAN clips load in
sorted order; building data.npz with a provided stats.npz keeps that normalization (and no longer crashes); target
resets only offset the reset envs and always respawn reached targets.
"""
import yaml


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_lafan(config_path, full_data=True):
    """LAFAN1 dataset (data/LAFAN1, relative to the working directory) for an A-MDM model config."""
    from amdm_interactive.core.dataset.lafan1_dataset import LAFAN1
    config = load_config(config_path)
    config['data']['load_full_data'] = full_data
    return LAFAN1(config)


def build_amdm(config_path, dataset, device):
    from amdm_interactive.core.model.amdm_model import AMDM
    return AMDM(config=load_config(config_path), dataset=dataset, device=device)
