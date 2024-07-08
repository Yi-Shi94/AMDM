import torch
import numpy as np
import math
import copy

def yaw_to_matrix(yaw):
    cs = np.cos(yaw)
    sn = np.sin(yaw)
    z = np.zeros_like(cs)
    o = np.ones_like(sn)
    out = np.array([[cs,z,sn],[z,o,z],[-sn,z,cs]])
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
    return np.concatenate((b1[...,None,:], b2[...,None,:], b3[...,None,:]), axis=-2)

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


def euler_to_matrix(order, euler_angle, degrees):
    """
    input
        theta1, theta2, theta3 = rotation angles in rotation order (degrees)
        oreder = rotation order of x,y,z　e.g. XZY rotation -- 'xzy'
    output
        3x3 rotation matrix (numpy array)
    """
    device = euler_angle.device
    if degrees:
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
