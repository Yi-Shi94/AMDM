"""Fit SMPL-H betas and a uniform scale to the LAFAN skeleton, for the viewer's SMPL body.

The SMPL-H model cannot be redistributed: download the "Extended SMPL+H model" from https://mano.is.tue.mpg.de
and point --source at its neutral model.npz. Writes body_models/smpl_lafan_fitted/SMPL_LAFAN_FITTED.npz (the
template with the fitted shape baked in, root-centred) and fit.json (betas, scale and per-bone errors).

    python -m amdm_interactive.fit_smpl_shape --source body_models/smplh/neutral/model.npz
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from amdm_interactive.smpl_body import PARENTS
from amdm_interactive.viewer import MAP

ROOT = Path(__file__).resolve().parents[1]


def fit(source, stats_path, out):
    out.mkdir(parents=True, exist_ok=True)
    with np.load(source, allow_pickle=True) as d:
        asset = {k: d[k] for k in d.files}
    with np.load(stats_path) as d:
        stats = {k: d[k] for k in d.files}
    # LAFAN skeleton rest pose from its offsets (centimetres -> metres).
    offsets = stats['joint_offset'] / 100.
    source_parents = np.full(22, -1, dtype=int)
    for a, b in stats['links']:
        parent, child = sorted((int(a), int(b)))
        source_parents[child] = parent
    skeleton = np.zeros((22, 3))
    for i, p in enumerate(source_parents):
        skeleton[i] = offsets[i] if p < 0 else skeleton[p] + offsets[i]
    # First 10 shape coefficients, with a strong Gaussian prior; one shared shape, no pose and no per-vertex stretch.
    shape_dirs = asset['shapedirs'][..., :10]
    dirs = np.einsum('jv,vcb->jcb', asset['J_regressor_prior'], shape_dirs)
    base = asset['J'][:24]
    # Match anatomically corresponding bone lengths plus hip and shoulder widths.
    edges = [(p, i) for i, p in enumerate(PARENTS) if p >= 0 and MAP[p] != MAP[i]] + [(1, 2), (13, 14)]
    target = np.array([np.linalg.norm(skeleton[MAP[b]] - skeleton[MAP[a]]) for a, b in edges])

    def lengths(joints):
        return np.array([np.linalg.norm(joints[b] - joints[a]) for a, b in edges])

    def residual(p):
        beta, scale = p[:-1], np.exp(p[-1])
        joints = (base + np.einsum('jcb,b->jc', dirs, beta)) * scale
        bones = (lengths(joints) - target) / np.maximum(target, .10)  # balanced across long and short bones
        return np.r_[bones, .30 * beta, .20 * p[-1]]

    n = dirs.shape[-1]
    result = least_squares(residual, np.zeros(n + 1),
                           bounds=(np.r_[np.full(n, -1.5), np.log(.85)], np.r_[np.full(n, 1.5), np.log(1.25)]),
                           max_nfev=1000, xtol=1e-12, ftol=1e-12, gtol=1e-12)
    beta, scale = result.x[:-1], float(np.exp(result.x[-1]))
    shaped_j = (base + np.einsum('jcb,b->jc', dirs, beta)) * scale
    shaped_v = (asset['v_template'] + np.einsum('vcb,b->vc', shape_dirs, beta)) * scale
    # Root-centre so the mesh and its joint binding share one frame; blend shapes now describe metre changes.
    shift = shaped_j[0].copy()
    asset.update(v_template=shaped_v - shift, J=shaped_j - shift, shapedirs=asset['shapedirs'] * scale,
                 posedirs=asset['posedirs'] * scale, fit_betas=beta, fit_scale=np.array(scale))
    np.savez_compressed(out / 'SMPL_LAFAN_FITTED.npz', **asset)
    before, after = lengths(base), lengths(shaped_j)
    report = dict(betas=beta.tolist(), scale=scale, success=bool(result.success),
                  mean_bone_error_before_cm=float(np.abs(before - target).mean() * 100),
                  mean_bone_error_after_cm=float(np.abs(after - target).mean() * 100),
                  max_bone_error_after_cm=float(np.abs(after - target).max() * 100),
                  bones=[dict(smpl_parent=a, smpl_child=b, target_m=float(t), before_m=float(v), after_m=float(w))
                         for (a, b), t, v, w in zip(edges, target, before, after)])
    (out / 'fit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'bones'}, indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', type=Path, required=True, help='SMPL-H neutral model.npz')
    p.add_argument('--stats', type=Path, default=ROOT / 'data/LAFAN1/stats.npz')
    p.add_argument('--out', type=Path, default=ROOT / 'body_models/smpl_lafan_fitted')
    a = p.parse_args()
    fit(a.source, a.stats, a.out)
