"""Turn a hand-drawn stroke into a FacingPathEnv path (30 Hz waypoints, velocity, facing) for one env.

Same limits as the training generator: 2.5 m/s^2 acceleration, lateral acceleration 3 m/s^2 (speed capped by the
stroke's curvature), facing offset rate-limited to 3 rad/s and clamped to pi * clamp((3 - v) / 1.5, 0, 1), so a
sideways/backward facing request fades out at speed. The path starts at the character's root; after the end it
holds the last point at zero velocity. All inputs and outputs are env-plane (x, z) coordinates.
"""
import math
import numpy as np
import torch

ACCEL, LATERAL, FACE_RATE, DS = 2.5, 3., 3., .05


def _resample(points, ds=DS):
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.r_[True, seg > 1e-6]
    points = points[keep]
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if s[-1] < ds:return points[:1], s[:1]
    grid = np.arange(0., s[-1], ds)
    return np.stack([np.interp(grid, s, points[:, i]) for i in range(2)], 1), grid


def _smooth(points, window=7):
    if len(points) < window:return points
    pad = window // 2
    padded = np.r_[np.repeat(points[:1], pad, 0), points, np.repeat(points[-1:], pad, 0)]
    kernel = np.ones(window) / window
    out = np.stack([np.convolve(padded[:, i], kernel, 'valid') for i in range(2)], 1)
    out[0], out[-1] = points[0], points[-1]
    return out


def build(root_xz, body_yaw, stroke_xz, speed, facing_offset, length, fps=30, start_speed=0., start_offset=0.):
    """Return (path (L, 2), vel (L, 2), facing (L,)) as float32 numpy arrays.

    start_speed / start_offset continue from the path being replaced (re-timing), so the speed and facing ramp
    from where they are instead of from standstill / forward."""
    dt = 1. / fps
    pts, s = _resample(np.r_[np.asarray(root_xz, float)[None], np.asarray(stroke_xz, float)])
    pts = _smooth(pts)
    pts, s = _resample(pts)
    path = np.repeat(pts[-1:], length, 0).astype(np.float32)
    vel = np.zeros((length, 2), np.float32)
    face = np.full(length, body_yaw, np.float32)
    if len(pts) < 3:
        path[:] = root_xz
        return path, vel, face
    tangent = np.gradient(pts, axis=0)
    heading = np.unwrap(np.arctan2(tangent[:, 1], tangent[:, 0]))
    curvature = np.abs(np.gradient(heading)) / DS
    vmax = np.minimum(speed, np.sqrt(LATERAL / np.maximum(curvature, 1e-6)))
    vmax[-1] = 0.
    for i in range(len(vmax) - 2, -1, -1):  # decelerate in time for corners and the end
        vmax[i] = min(vmax[i], math.sqrt(vmax[i + 1] ** 2 + 2 * ACCEL * DS))
    v_grid = np.zeros_like(vmax)
    v_grid[0] = min(start_speed, vmax[0])
    for i in range(1, len(vmax)):           # accelerate from standstill
        v_grid[i] = min(vmax[i], math.sqrt(v_grid[i - 1] ** 2 + 2 * ACCEL * DS))
    total, pos_s, rel = s[-1], 0., float(start_offset)
    for k in range(length):
        if pos_s >= total - 1e-3:
            path[k:] = pts[-1]
            face[k:] = face[k - 1] if k else body_yaw
            break
        v = max(float(np.interp(pos_s, s, v_grid)), .05)
        h = float(np.interp(pos_s, s, heading))
        path[k] = [np.interp(pos_s, s, pts[:, 0]), np.interp(pos_s, s, pts[:, 1])]
        vel[k] = v * np.array([math.cos(h), math.sin(h)])
        rel = rel + float(np.clip((facing_offset - rel + math.pi) % (2 * math.pi) - math.pi, -FACE_RATE * dt, FACE_RATE * dt))
        limit = math.pi * min(1., max(0., (3. - v) / 1.5))
        rel = min(max(rel, -limit), limit)
        face[k] = h + rel
        pos_s += v * dt
    return path, vel, face


def install(env, path, vel, face, index=0):
    """Put a built path into env slot `index` and restart its path clock."""
    dev = env.path.device
    env.path[index] = torch.as_tensor(path, device=dev)
    env.path_vel[index] = torch.as_tensor(vel, device=dev)
    env.path_facing[index] = torch.as_tensor(face, device=dev)
    env.path_t[index] = 0
    env.timestep = 0


def stand_still(env, index=0):
    """Hold the current root position and body facing (used before the first stroke and on stop)."""
    L = env.path_len
    root = env.root_xz[index].detach().cpu().numpy()
    yaw = float(env.body_yaw()[index])
    install(env, np.repeat(root[None], L, 0).astype(np.float32), np.zeros((L, 2), np.float32),
            np.full(L, yaw, np.float32), index)


def finished(env, index=0, margin=None):
    """True when the path has (almost) run out: no moving waypoint left, or fewer than `margin` frames of buffer
    (default: the policy's look-ahead, 2.5 s) before the end."""
    t = int(env.path_t[index])
    margin = int(env.lookahead[-1]) + 1 if margin is None else margin
    if t >= env.path_len - 1 - margin:
        return True
    return not bool((env.path_vel[index, t:].norm(dim=-1) > 1e-3).any())


def remaining(env, index=0, step=3):
    """Env-plane points of the path still ahead (from the current waypoint to where motion ends), or None."""
    t = int(env.path_t[index])
    speed = env.path_vel[index, t:].norm(dim=-1)
    moving = (speed > 1e-3).nonzero().flatten()
    if len(moving) == 0:return None
    pts = env.path[index, t:t + int(moving[-1]) + 2].detach().cpu().numpy()
    return np.r_[pts[::step], pts[-1:]]


def random_path(env, index=0, continue_motion=False):
    """A training-generator path (varying speed and facing) shifted to start at the character.

    continue_motion: start at the current waypoint's speed, heading and facing offset (seamless chaining)."""
    kwargs = {}
    if continue_motion:
        speed, offset = current_motion(env, index)
        t = int(env.path_t[index])
        v = env.path_vel[index, t]
        heading = math.atan2(float(v[1]), float(v[0])) if speed > 1e-3 else float(env.body_yaw()[index])
        if env.facing_command == 'forward':
            offset = 0.
        kwargs = dict(start_speed=speed, start_heading=heading, start_offset=offset)
    path, vel, face = env.sample_paths(torch.arange(1, device=env.path.device), **kwargs)
    path = path[0] + env.root_xz[index]
    install(env, path, vel[0], face[0], index)


def current_motion(env, index=0):
    """(commanded speed, facing offset from the tangent) at the current waypoint, for re-timing."""
    t = int(env.path_t[index])
    v = env.path_vel[index, t]
    speed = float(v.norm())
    if speed < 1e-3:return 0., 0.
    tangent = math.atan2(float(v[1]), float(v[0]))
    return speed, (float(env.path_facing[index, t]) - tangent + math.pi) % (2 * math.pi) - math.pi
