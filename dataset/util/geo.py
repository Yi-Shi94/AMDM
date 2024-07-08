import torch
import numpy as np
import math
import copy


#### torch jit ####
@torch.jit.script
def normalize_angle(x):
    # type: (Tensor) -> Tensor
    return torch.atan2(torch.sin(x), torch.cos(x))

@torch.jit.script
def normalize(x, eps: float = 1e-9):
    # type: (Tensor, float) -> Tensor
    return x / x.norm(p=2, dim=-1).clamp(min=eps, max=None).unsqueeze(-1)

@torch.jit.script
def quat_unit(a):
    # type: (Tensor) -> Tensor
    return normalize(a)

@torch.jit.script
def normalize_exp_map(exp_map):
    # type: (Tensor) -> Tensor
    angle = torch.norm(exp_map, dim=-1)
    angle = angle.clamp_min(1e-9)
    norm_angle = normalize_angle(angle)
    scale = norm_angle / angle
    norm_exp_map = exp_map * scale.unsqueeze(-1)
    return norm_exp_map

@torch.jit.script
def quat_conjugate(q):
    return torch.cat([-q[..., :3], q[..., 3:]], dim=-1)

@torch.jit.script
def quat_mul(a, b):
    # type: (Tensor, Tensor) -> Tensor
    assert a.shape == b.shape

    x1, y1, z1, w1 = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    x2, y2, z2, w2 = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    ww = (z1 + x1) * (x2 + y2)
    yy = (w1 - y1) * (w2 + z2)
    zz = (w1 + y1) * (w2 - z2)
    xx = ww + yy + zz
    qq = 0.5 * (xx + (z1 - x1) * (x2 - y2))
    w = qq - ww + (z1 - y1) * (y2 - z2)
    x = qq - xx + (x1 + w1) * (x2 + w2)
    y = qq - yy + (w1 - x1) * (y2 + z2)
    z = qq - zz + (z1 + y1) * (w2 - x2)

    quat = torch.stack([x, y, z, w], dim=-1)
    return quat

@torch.jit.script
def quat_rotate(q, v):
    # type: (Tensor, Tensor) -> Tensor
    shape = q.shape
    q_w = q[:, -1]
    q_vec = q[:, :3]
    a = v * (2.0 * q_w ** 2 - 1.0).unsqueeze(-1)
    b = torch.cross(q_vec, v, dim=-1) * q_w.unsqueeze(-1) * 2.0
    c = q_vec * \
        torch.bmm(q_vec.view(shape[0], 1, 3), v.view(
            shape[0], 3, 1)).squeeze(-1) * 2.0
    return a + b + c

@torch.jit.script
def quat_to_axis_angle(q):
    # type: (Tensor) -> Tuple[Tensor, Tensor]
    min_theta = 1e-5
    qx, qy, qz, qw = 0, 1, 2, 3

    sin_theta = torch.sqrt(1 - q[..., qw] * q[..., qw])
    angle = 2 * torch.acos(q[..., qw])
    angle = normalize_angle(angle)
    sin_theta_expand = sin_theta.unsqueeze(-1)
    axis = q[..., qx:qw] / sin_theta_expand

    mask = torch.abs(sin_theta) > min_theta
    default_axis = torch.zeros_like(axis)
    default_axis[..., -1] = 1

    angle = torch.where(mask, angle, torch.zeros_like(angle))
    mask_expand = mask.unsqueeze(-1)
    axis = torch.where(mask_expand, axis, default_axis)
    return axis, angle

@torch.jit.script
def axis_angle_to_quat(axis, angle):
    # type: (Tensor, Tensor) -> Tensor
    theta = (angle / 2).unsqueeze(-1)
    xyz = normalize(axis) * theta.sin()
    w = theta.cos()
    return quat_unit(torch.cat([xyz, w], dim=-1))

@torch.jit.script
def exp_map_to_axis_angle(exp_map):
    # type: (Tensor) -> Tuple[Tensor, Tensor]
    min_theta = 1e-5
    
    angle = torch.norm(exp_map, dim=-1)
    angle_exp = torch.unsqueeze(angle, dim=-1)
    axis = exp_map / angle_exp
    angle = normalize_angle(angle)

    default_axis = torch.zeros_like(exp_map)
    default_axis[..., -1] = 1

    mask = torch.abs(angle) > min_theta
    angle = torch.where(mask, angle, torch.zeros_like(angle))
    mask_expand = mask.unsqueeze(-1)
    axis = torch.where(mask_expand, axis, default_axis)

    return axis, angle

@torch.jit.script
def exp_map_to_quat(exp_map):
    axis, angle = exp_map_to_axis_angle(exp_map)
    quat = axis_angle_to_quat(axis, angle)
    return quat


@torch.jit.script
def axis_angle_to_exp_map(axis, angle):
    # type: (Tensor, Tensor) -> Tensor
    angle_expand = angle.unsqueeze(-1)
    exp_map = angle_expand * axis
    return exp_map

@torch.jit.script
def quat_to_exp_map(q):
    # type: (Tensor) -> Tensor
    axis, angle = quat_to_axis_angle(q)
    exp_map = axis_angle_to_exp_map(axis, angle)
    return exp_map


@torch.jit.script
def quat_to_tan_norm(q):
    # type: (Tensor) -> Tensor
    ref_tan = torch.zeros_like(q[..., 0:3])
    ref_tan[..., 0] = 1
    tan = quat_rotate(q, ref_tan)
    
    ref_norm = torch.zeros_like(q[..., 0:3])
    ref_norm[..., -1] = 1
    norm = quat_rotate(q, ref_norm)
    
    norm_tan = torch.cat([tan, norm], dim=len(tan.shape) - 1)
    return norm_tan


@torch.jit.script
def quat_to_rotmat(q):
    i, j, k, r= torch.unbind(q, -1)
    two_s = 2.0 / (q * q).sum(-1)
    o = torch.stack(
        (
            1 - two_s * (j * j + k * k),
            two_s * (i * j - k * r),
            two_s * (i * k + j * r),
            two_s * (i * j + k * r),
            1 - two_s * (i * i + k * k),
            two_s * (j * k - i * r),
            two_s * (i * k - j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(q.shape[:-1] + (3, 3))


def rotmat_to_exp_map(matrix: torch.Tensor) -> torch.Tensor:
    """
    Convert rotations given as rotation matrices to axis/angle.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).

    Returns:
        Rotations given as a vector in axis angle form, as a tensor
            of shape (..., 3), where the magnitude is the angle
            turned anticlockwise in radians around the vector's
            direction.
    """
    quat = rotmat_to_quat(matrix)
    exp_map = normalize_exp_map(quat_to_exp_map(quat))

    return exp_map


def standardize_quaternion(quaternions: torch.Tensor) -> torch.Tensor:
    """
    Convert a unit quaternion to a standard form: one in which the real
    part is non negative.

    Args:
        quaternions: Quaternions with real part first,
            as tensor of shape (..., 4).

    Returns:
        Standardized quaternions as tensor of shape (..., 4).
    """
    quat = torch.where(quaternions[..., 0:1] < 0, -quaternions, quaternions)
    quat_new = torch.zeros_like(quat)
    quat_new[...,:3] = quat[...,1:]
    quat_new[...,3] = quat[...,0]
    return quat


def _sqrt_positive_part(x: torch.Tensor) -> torch.Tensor:
    """
    Returns torch.sqrt(torch.max(0, x))
    but with a zero subgradient where x is 0.
    """
    ret = torch.zeros_like(x)
    positive_mask = x > 0
    ret[positive_mask] = torch.sqrt(x[positive_mask])
    return ret


def rotmat_to_quat(matrix: torch.Tensor) -> torch.Tensor:
    """
    Convert rotations given as rotation matrices to quaternions.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).

    Returns:
        quaternions with real part first, as tensor of shape (..., 4).
    """
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")

    batch_dim = matrix.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(
        matrix.reshape(batch_dim + (9,)), dim=-1
    )

    q_abs = _sqrt_positive_part(
        torch.stack(
            [
                1.0 + m00 + m11 + m22,
                1.0 + m00 - m11 - m22,
                1.0 - m00 + m11 - m22,
                1.0 - m00 - m11 + m22,
            ],
            dim=-1,
        )
    )

    # we produce the desired quaternion multiplied by each of r, i, j, k
    quat_by_ijkr = torch.stack(
        [
          
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and
            #  `int`.
            torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], dim=-1),
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and
            #  `int`.
            torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], dim=-1),
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and
            #  `int`.
            torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], dim=-1),
              # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and
            #  `int`.
            torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], dim=-1),
        ],
        dim=-2,
    )

    # We floor here at 0.1 but the exact level is not important; if q_abs is small,
    # the candidate won't be picked.
    flr = torch.tensor(0.1).to(dtype=q_abs.dtype, device=q_abs.device)
    quat_candidates = quat_by_ijkr / (2.0 * q_abs[..., None].max(flr))

    # if not for numerical problems, quat_candidates[i] should be same (up to a sign),
    # forall i; we pick the best-conditioned one (with the largest denominator)
    out = quat_candidates[
        torch.nn.functional.one_hot(q_abs.argmax(dim=-1), num_classes=4) > 0.5, :
    ].reshape(batch_dim + (4,))
    return standardize_quaternion(out)


@torch.jit.script
def m6d_to_rotmat(m6d):
    a1, a2 = m6d[..., :3], m6d[..., 3:]
    b1 = torch.nn.functional.normalize(a1, dim=-1)
    b2 = a2 - (b1 * a2).sum(-1, keepdim=True) * b1
    b2 = torch.nn.functional.normalize(b2, dim=-1)
    b3 = torch.cross(b1, b2, dim=-1)
    return torch.stack((b1, b2, b3), dim=-2)

@torch.jit.script
def rotmat_to_m6d(rotmat):
    batch_dim = rotmat.size()[:-2]
    return rotmat[..., :2, :].clone().reshape(batch_dim + (6,))

@torch.jit.script
def quat_to_6d(q):
    rotmat = quat_to_rotmat(q)
    m6d = rotmat_to_m6d(rotmat)
    return m6d

@torch.jit.script
def quat_rotate(q, v):
    # type: (Tensor, Tensor) -> Tensor
    shape = q.shape
    q_w = q[:, -1]
    q_vec = q[:, :3]
    a = v * (2.0 * q_w ** 2 - 1.0).unsqueeze(-1)
    b = torch.cross(q_vec, v, dim=-1) * q_w.unsqueeze(-1) * 2.0
    c = q_vec * \
        torch.bmm(q_vec.view(shape[0], 1, 3), v.view(
            shape[0], 3, 1)).squeeze(-1) * 2.0
    return a + b + c

@torch.jit.script
def sepr_x_angle(q):
    ref_dir = torch.zeros_like(q[..., 0:3])
    ref_dir[..., 1] = 1
    rot_dir = quat_rotate(q, ref_dir)
    heading = torch.atan2(rot_dir[..., 2], rot_dir[..., 1])
    return heading

@torch.jit.script
def sepr_x_quat(q):
    # type: (Tensor) -> Tensor
    heading = sepr_x_angle(q)
    axis = torch.zeros_like(q[..., 0:3])
    axis[..., 0] = 1

    heading_q = axis_angle_to_quat(axis, heading)
    return heading_q

@torch.jit.script
def sepr_y_angle(q):
    ref_dir = torch.zeros_like(q[..., 0:3])
    ref_dir[..., 0] = 1
    rot_dir = quat_rotate(q, ref_dir)
    heading = torch.atan2(rot_dir[..., 2], rot_dir[..., 0])
    return heading

@torch.jit.script
def sepr_y_quat(q):
    # type: (Tensor) -> Tensor
    heading = sepr_y_angle(q)
    axis = torch.zeros_like(q[..., 0:3])
    axis[..., 1] = 1

    heading_q = axis_angle_to_quat(axis, heading)
    return heading_q


@torch.jit.script
def sepr_z_angle(q):
    ref_dir = torch.zeros_like(q[..., 0:3])
    ref_dir[..., 0] = 1
    rot_dir = quat_rotate(q, ref_dir)
    heading = torch.atan2(rot_dir[..., 1], rot_dir[..., 0])
    return heading

@torch.jit.script
def sepr_z_quat(q):
    # type: (Tensor) -> Tensor
    heading = sepr_z_angle(q)
    axis = torch.zeros_like(q[..., 0:3])
    axis[..., 2] = 1

    heading_q = axis_angle_to_quat(axis, heading)
    return heading_q


@torch.jit.script
def calc_heading(q):
    ref_dir = torch.zeros_like(q[..., 0:3])
    ref_dir[..., 0] = 1
    rot_dir = quat_rotate(q, ref_dir)
    heading = torch.atan2(rot_dir[..., 1], rot_dir[..., 0])
    return heading

@torch.jit.script
def calc_heading_quat(q):
    # type: (Tensor) -> Tensor
    heading = calc_heading(q)
    axis = torch.zeros_like(q[..., 0:3])
    axis[..., 2] = 1

    heading_q = axis_angle_to_quat(axis, heading)
    return heading_q

@torch.jit.script
def quat_diff(q0, q1):
    dq = quat_mul(q1, quat_conjugate(q0))
    return dq

@torch.jit.script
def quat_diff_angle(q0, q1):
    dq = quat_mul(q1, quat_conjugate(q0))
    _, angle = quat_to_axis_angle(dq)
    return angle


@torch.jit.script
def matrix_to_axis_angle(R):
    # type: (Tensor) -> Tuple[Tensor, Tensor]
    trace = R[...,0,0] +  R[...,1,1] +  R[...,2,2]
    angle = torch.acos((trace - 1) / 2)
    rx = R[..., 2, 1] - R[..., 1, 2]
    ry = R[..., 0, 2] - R[..., 2, 0]
    rz = R[..., 1, 0] - R[..., 0, 1]
    axis = torch.stack([rx, ry, rz], dim=-1)
    norm = torch.norm(axis, dim =-1, keepdim=True)
    mask = norm < 1e-5
    norm[mask] = 1.0 
    axis = axis / norm
    return axis, angle

@torch.jit.script
def matrix_to_quat(R):
    # type: (Tensor) -> Tensor
    axis, angle = matrix_to_axis_angle(R)
    quat = axis_angle_to_quat(axis, angle)
    return quat


#### numpy #### 
def sepr_rot_heading(rotation):
    global_heading = -np.arctan2(rotation[...,0,2], rotation[...,2,2]) 
    global_heading_rot = np.array([rot_yaw(-x) for x in global_heading])
    return global_heading_rot, np.matmul(global_heading_rot, rotation) 


def angle_difference(angle1, angle2):
    """
    Calculate the difference between two angles, handling the discontinuity around 0 and 2*pi.

    Args:
    angle1 (float): First angle in radians.
    angle2 (float): Second angle in radians.

    Returns:
    float: The smallest difference between the two angles.
    """
    # Normalize angles to be within [0, 2*pi)
    angle1 = angle1 % (2 * math.pi)
    angle2 = angle2 % (2 * math.pi)

    # Calculate the difference
    diff = angle1 - angle2

    # Adjust for the discontinuity
    if diff > math.pi:
        diff -= 2 * math.pi
    elif diff < -math.pi:
        diff += 2 * math.pi

    return diff


def rot_roll(roll):
    cs = np.cos(roll)
    sn = np.sin(roll)
    return np.array([[1, 0, 0],
                    [0, cs, -sn],
                    [0, sn, cs]])

def rot_pitch(pitch):
    cs = np.cos(pitch)
    sn = np.sin(pitch)
    return np.array([[cs, -sn, 0],
                      [sn, cs, 0],
                      [0, 0, 1]])


def rot_yaw(yaw):
    cs = np.cos(yaw)
    sn = np.sin(yaw)
    return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])


def exp_map_to_rot(exp_map):
    """
    Converts an exponent map to a rotation matrix.
    
    Args:
        exp_map: A 3x1 numpy array representing the exponent map.
        
    Returns:
        A 3x3 numpy array representing the corresponding rotation matrix.
    """
    def e2r(exp_map):
        theta = np.linalg.norm(exp_map)
        if theta < 1e-12:
            return np.eye(3)
        else:
            v = exp_map / theta
            skew_v = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
            R = np.eye(3) + np.sin(theta) * skew_v + (1 - np.cos(theta)) * np.dot(skew_v, skew_v)
            return R

    if len(exp_map.shape) == 3:
        N = exp_map.shape[0]
        rotmats = np.zeros(N,3,3)
        for i in range(N):
            rotmat = e2r(exp_map[i])
            rotmats[i] = rotmat

        return rotmats
    else:
        return e2r(exp_map)
    
def rad_to_matrix_2d(rad):
    cs = np.cos(rad)
    sn = np.sin(rad)
    out = np.array([[cs,-sn],[sn,cs]])
    if len(out.shape) == 2:
        return out
    out = np.transpose(out,(2,0,1))
    return out

def yaw_to_matrix(yaw):
    cs = np.cos(yaw)
    sn = np.sin(yaw)
    z = np.zeros_like(cs)
    o = np.ones_like(sn)
    out = np.array([[cs,z,sn],[z,o,z],[-sn,z,cs]])
    if len(out.shape) == 2:
        return out
    return np.transpose(out,(2,0,1))

def pitch_to_matrix(pitch):
    cs = np.cos(pitch)
    sn = np.sin(pitch)
    z = np.zeros_like(cs)
    o = np.ones_like(sn)
    out = np.array([[cs,-sn, z],[sn,cs,z],[z,z,o]])
    if len(out.shape) == 2:
        return out
    return np.transpose(out,(2,0,1))

def rotation_6d_to_matrix(rotation):
    """
    Converts 6D rotation representation by Zhou et al. [1] to rotation matrix
    using Gram--Schmidt orthogonalization per Section B of [1].
    Args:
        d6: 6D rotation representation, of size (*, 6)

    Returns:
        batch of rotation matrices of size (*, 3, 3)

    [1] Zhou, Y., Barnes, C., Lu, J., Yang, J., & Li, H.
    On the Continuity of Rotation Representations in Neural Networks.
    IEEE Conference on Computer Vision and Pattern Recognition, 2019.
    Retrieved from http://arxiv.org/abs/1812.07035
    """
    nfrm = rotation.shape[0]
    rotation = np.reshape(rotation,(nfrm,-1,6))
    
    a1, a2 = rotation[..., :3], rotation[..., 3:]
    b1 = a1/np.linalg.norm(a1, axis=-1)[...,None]
    
    b2 = a2 - (b1 * a2).sum(axis=-1)[...,None] * b1
    b2 = b2/np.linalg.norm(b2, axis=-1)[...,None]
    
    b3 = np.cross(b1, b2, axis=-1)
    return np.concatenate((b1[...,:], b2[...,:], b3[...,:]), axis=-2)

def rotation_matrix_to_6d(rotation):
    batch_dim = rotation.shape[:-2]
    return copy.deepcopy(rotation[..., :2, :]).reshape(batch_dim + (6,))


def _index_from_letter(letter: str) -> int:
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(
    axis: str, other_axis: str, data, horizontal: bool, tait_bryan: bool):
    """
    Extract the first or third Euler angle from the two members of
    the matrix which are positive constant times its sine and cosine.

    Args:
        axis: Axis label "X" or "Y or "Z" for the angle we are finding.
        other_axis: Axis label "X" or "Y or "Z" for the middle axis in the
            convention.
        data: Rotation matrices as tensor of shape (..., 3, 3).
        horizontal: Whether we are looking for the angle for the third axis,
            which means the relevant entries are in the same row of the
            rotation matrix. If not, they are in the same column.
        tait_bryan: Whether the first and third axes in the convention differ.

    Returns:
        Euler Angles in radians for each matrix in data as a tensor
        of shape (...).
    """

    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[..., i1], data[..., i2])
    if tait_bryan:
        return np.arctan2(-data[..., i2], data[..., i1])
    return np.arctan2(data[..., i2], -data[..., i1])


def rotation_matrix_to_euler_pt(matrix: torch.Tensor, convention: str) -> torch.Tensor:
    """
    Convert rotations given as rotation matrices to Euler angles in radians.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).
        convention: Convention string of three uppercase letters.

    Returns:
        Euler angles in radians as tensor of shape (..., 3).
    """
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    for letter in convention:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    i0 = _index_from_letter(convention[0])
    i2 = _index_from_letter(convention[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = torch.asin(
            matrix[..., i0, i2] * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = torch.acos(matrix[..., i0, i0])

    o = (
        _angle_from_tan(
            convention[0], convention[1], matrix[..., i2], False, tait_bryan
        ),
        central_angle,
        _angle_from_tan(
            convention[2], convention[1], matrix[..., i0, :], True, tait_bryan
        ),
    )
    return torch.stack(o, -1)

def rotation_matrix_to_euler(matrix, order):
    """
    Convert rotations given as rotation matrices to Euler angles in radians.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).
        order: Convention string of three uppercase letters.

    Returns:
        Euler angles in radians as tensor of shape (..., 3).
    """
    if len(order) != 3:
        raise ValueError("order must have 3 letters.")
    
    if order[1] in (order[0], order[2]):
        raise ValueError(f"Invalid order {order}.")
    
    for letter in order:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    
    if matrix.shape[-1] != 3 or matrix.shape[-2] != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    
    i0 = _index_from_letter(order[0])
    i2 = _index_from_letter(order[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = np.arcsin(
            matrix[..., i0, i2] * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = np.arccos(matrix[..., i0, i0])
    
    central_angle = central_angle[...,None]
    o = (
        _angle_from_tan(
            order[0], order[1], matrix[..., i2], False, tait_bryan
        )[...,None],
        central_angle,
        _angle_from_tan(
            order[2], order[1], matrix[..., i0, :], True, tait_bryan
        )[...,None],
    )
    return np.concatenate(o, -1)


def euler_to_matrix(order, euler_angle, input_degree=True):
    """
    input
        theta1, theta2, theta3 = rotation angles in rotation order (degrees)
        oreder = rotation order of x,y,z　e.g. XZY rotation -- 'xzy'
    output
        3x3 rotation matrix (numpy array)
    """
    device = euler_angle.device
    if input_degree:
        euler_angle = euler_angle/180*math.pi
    #print(euler_angle.grad,'mat')
    
    matrix = torch.ones(3,3).to(device)
    c1 = torch.cos(euler_angle[0])
    s1 = torch.sin(euler_angle[0])
    c2 = torch.cos(euler_angle[1])
    s2 = torch.sin(euler_angle[1])
    c3 = torch.cos(euler_angle[2])
    s3 = torch.sin(euler_angle[2])
    
    if order=='XYZ':
        matrix=torch.tensor([[c2*c3, -c2*s3, s2],
                         [c1*s3+c3*s1*s2, c1*c3-s1*s2*s3, -c2*s1],
                         [s1*s3-c1*c3*s2, c3*s1+c1*s2*s3, c1*c2]])
    elif order=='XZY':
        matrix=torch.tensor([[c2*c3, -s2, c2*s3],
                         [s1*s3+c1*c3*s2, c1*c2, c1*s2*s3-c3*s1],
                         [c3*s1*s2-c1*s3, c2*s1, c1*c3+s1*s2*s3]])
    elif order=='YXZ':
        matrix=torch.tensor([[c1*c3+s1*s2*s3, c3*s1*s2-c1*s3, c2*s1],
                         [c2*s3, c2*c3, -s2],
                         [c1*s2*s3-c3*s1, c1*c3*s2+s1*s3, c1*c2]])
    elif order=='YZX':
        matrix=torch.tensor([[c1*c2, s1*s3-c1*c3*s2, c3*s1+c1*s2*s3],
                         [s2, c2*c3, -c2*s3],
                         [-c2*s1, c1*s3+c3*s1*s2, c1*c3-s1*s2*s3]])
    elif order=='ZYX':
        matrix[0,0] *= c1*c2
        matrix[0,1] *= c1*s2*s3-c3*s1
        matrix[0,2] *= s1*s3+c1*c3*s2

        matrix[1,0] *= c2*s1
        matrix[1,1] *= c1*c3+s1*s2*s3
        matrix[1,2] *= c3*s1*s2-c1*s3

        matrix[2,0] *= -s2
        matrix[2,1] *= c2*s3
        matrix[2,2] *= c2*c3

    elif order=='ZXY':
        matrix=torch.tensor([[c1*c3-s1*s2*s3, -c2*s1, c1*s3+c3*s1*s2],
                         [c3*s1+c1*s2*s3, c1*c2, s1*s3-c1*c3*s2],
                         [-c2*s3, s2, c2*c3]])
    return matrix


def _index_from_letter(letter: str) -> int:
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(
    axis: str, other_axis: str, data, horizontal: bool, tait_bryan: bool):
    """
    Extract the first or third Euler angle from the two members of
    the matrix which are positive constant times its sine and cosine.

    Args:
        axis: Axis label "X" or "Y or "Z" for the angle we are finding.
        other_axis: Axis label "X" or "Y or "Z" for the middle axis in the
            convention.
        data: Rotation matrices as tensor of shape (..., 3, 3).
        horizontal: Whether we are looking for the angle for the third axis,
            which means the relevant entries are in the same row of the
            rotation matrix. If not, they are in the same column.
        tait_bryan: Whether the first and third axes in the convention differ.

    Returns:
        Euler Angles in radians for each matrix in data as a tensor
        of shape (...).
    """

    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[..., i1], data[..., i2])
    if tait_bryan:
        return np.arctan2(-data[..., i2], data[..., i1])
    return np.arctan2(data[..., i2], -data[..., i1])


def matrix_to_euler(matrix, order):
    """
    Convert rotations given as rotation matrices to Euler angles in radians.

    Args:
        matrix: Rotation matrices as tensor of shape (..., 3, 3).
        order: Convention string of three uppercase letters.

    Returns:
        Euler angles in radians as tensor of shape (..., 3).
    """
    if len(order) != 3:
        raise ValueError("order must have 3 letters.")
    
    if order[1] in (order[0], order[2]):
        raise ValueError(f"Invalid order {order}.")
    
    for letter in order:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    
    if matrix.shape[-1] != 3 or matrix.shape[-2] != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    
    i0 = _index_from_letter(order[0])
    i2 = _index_from_letter(order[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = np.arcsin(
            matrix[..., i0, i2] * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = np.arccos(matrix[..., i0, i0])
    
    central_angle = central_angle[...,None]
    o = (
        _angle_from_tan(
            order[0], order[1], matrix[..., i2], False, tait_bryan
        )[...,None],
        central_angle,
        _angle_from_tan(
            order[2], order[1], matrix[..., i0, :], True, tait_bryan
        )[...,None],
    )
    return np.concatenate(o, -1)
