"""Capsule person: the primitive human body used for the A-MDM people in GenerativeWBC's dodge task.

DeepMimic-style shapes (radii after MimicKit's ~1.65 m humanoid, scaled by `size`) placed on the 22 LAFAN joints:
three side-to-side torso capsules (hip, waist, chest), a neck capsule and a short head capsule on top of it,
capsules for clavicles, upper and lower arms and legs (upper arms and thighs thicker than forearms and shins), hand spheres, and a
heel-to-toe box per foot whose sole is flat on the floor when standing. Compared with the dodge task, the head is
split into neck + head, the upper arms and thighs are thicker and the feet are recalibrated, to read more like a
person. No body model
download is needed. Drawn as MuJoCo scene geoms; the scene has the same floor and light as the SMPL body.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from .smpl_body import add_shadow_settings

RADII_HEIGHT_M = 1.65
HEAD_LENGTH_M, HEAD_RADIUS_M = 0.09, 0.085  # head capsule ends this far above the Head joint (neck -> head line)
NECK_RADIUS_M = 0.05
THIGH_RADIUS_M, SHIN_RADIUS_M = 0.075, 0.052
UPPER_ARM_RADIUS_M, FOREARM_RADIUS_M = 0.058, 0.04
FOOT_W = 0.09
# Foot sole, calibrated on LAFAN standing frames (both feet planted, body still): world up expressed in the foot
# joint's BVH frame is (-0.34, 0.94, 0) (the ankle -> toe axis slopes ~20 deg down), the ankle is ~6 cm above the
# floor and the toe joint on it. The box sole is that plane, so a standing foot is flat on the ground.
SOLE_UP_BVH = np.array([-0.338, 0.941, 0.])
SOLE_PITCH = float(np.arctan2(-SOLE_UP_BVH[0], SOLE_UP_BVH[1]))  # ~20 deg between the ankle -> toe line and the sole
ANKLE_HEIGHT_M = 0.067  # 6 cm measured + 7 mm so the median standing sole touches the floor
HEEL_BACK_M, TOE_FRONT_M = 0.04, 0.03       # sole extends this far behind the ankle / past the toe joint
COLOR = (0.85, 0.65, 0.5, 1.)


def _unit(v):
    return v / max(np.linalg.norm(v), 1e-6)


def shapes(joints, rotations, names, size=1.):
    """World LAFAN joints (22, 3) and global joint rotations (22, 3, 3) -> (capsules, boxes).

    capsules: list of (start, end, radius), a sphere when start == end; boxes: list of (centre, rotation, full size).
    """
    k = size
    J = lambda name: joints[names.index(name)]
    lerp = lambda a, b, t: a + (b - a) * t
    up = _unit(J('Spine') - J('Hips'))
    caps = []
    hip_side = _unit(J('LeftUpLeg') - J('RightUpLeg'))
    arm_side = _unit(J('LeftArm') - J('RightArm'))
    waist_side = _unit(hip_side + arm_side)
    pelvis = J('Hips') + up * 0.04 * k
    caps.append((pelvis - hip_side * 0.07 * k, pelvis + hip_side * 0.07 * k, 0.095))
    caps.append((J('Spine1') - waist_side * 0.06 * k, J('Spine1') + waist_side * 0.06 * k, 0.09))
    chest = lerp(J('Spine2'), J('Neck'), 0.25)
    caps.append((chest - arm_side * 0.08 * k, chest + arm_side * 0.08 * k, 0.10))
    head_up = _unit(J('Head') - J('Neck'))
    caps.append((lerp(J('Spine2'), J('Neck'), 0.85), lerp(J('Neck'), J('Head'), 0.6), NECK_RADIUS_M))  # short neck
    # Head: from 3/4 of the way up the neck bone to HEAD_LENGTH_M above the Head joint (top ~17.5 cm above it).
    caps.append((lerp(J('Neck'), J('Head'), 0.75), J('Head') + head_up * HEAD_LENGTH_M * k, HEAD_RADIUS_M))
    boxes = []
    for side in ('Left', 'Right'):
        caps.append((lerp(J(f'{side}Shoulder'), J(f'{side}Arm'), 0.2), J(f'{side}Arm'), 0.045))
        caps.append((lerp(J(f'{side}Arm'), J(f'{side}ForeArm'), 0.1), lerp(J(f'{side}Arm'), J(f'{side}ForeArm'), 0.85), UPPER_ARM_RADIUS_M))
        caps.append((lerp(J(f'{side}ForeArm'), J(f'{side}Hand'), 0.12), J(f'{side}Hand'), FOREARM_RADIUS_M))
        hand = J(f'{side}Hand') + _unit(J(f'{side}Hand') - J(f'{side}ForeArm')) * 0.05 * k
        caps.append((hand, hand, 0.04))
        caps.append((lerp(J(f'{side}UpLeg'), J(f'{side}Leg'), 0.12), lerp(J(f'{side}UpLeg'), J(f'{side}Leg'), 0.86), THIGH_RADIUS_M))
        caps.append((lerp(J(f'{side}Leg'), J(f'{side}Foot'), 0.07), lerp(J(f'{side}Leg'), J(f'{side}Foot'), 0.85), SHIN_RADIUS_M))  # ends ~1 cm above the foot
        # Foot box: the sole frame comes from the ankle -> toe line (well determined) and world up, not from the
        # foot joint's full rotation, whose twist about that line is unconstrained by the positions and can spin.
        # The sole is the line's vertical plane rotated by the calibrated pitch, so a standing foot is flat.
        ankle, toe = J(f'{side}Foot'), J(f'{side}Toe')
        d = _unit(toe - ankle)
        lateral = np.cross(np.array([0., 0., 1.]), d)
        if np.linalg.norm(lateral) < 1e-3:  # foot pointing straight up/down: fall back to the joint rotation
            lateral = rotations[names.index(f'{side}Foot')][:, 2]
        y = _unit(lateral)
        u = np.cross(d, y)  # perpendicular to the line, in its vertical plane, pointing up
        n = np.cos(SOLE_PITCH) * u - np.sin(SOLE_PITCH) * d
        x = np.cross(y, n)
        sole = ankle - n * ANKLE_HEIGHT_M * k
        heel = sole - x * HEEL_BACK_M * k
        front = toe - n * np.dot(toe - sole, n) + x * TOE_FRONT_M * k
        full = np.array([np.dot(front - heel, x), FOOT_W * k, ANKLE_HEIGHT_M * k])  # top of the box at the ankle
        centre = 0.5 * (heel + front) + n * 0.5 * full[2]
        fu = n
        reach = 0.5 * (full[0] * abs(x[2]) + full[1] * abs(y[2]) + full[2] * abs(fu[2]))
        centre[2] = max(centre[2], reach)  # lift (never lower) so no corner is below the floor
        boxes.append((centre, np.stack((x, y, fu), axis=1), full))
    return [(a, b, rad * k) for a, b, rad in caps], boxes


class CapsuleBody:
    """MuJoCo scene (floor + light) with the capsule person drawn as scene geoms each frame."""

    def __init__(self, names, size=1.):
        self.names, self.size = list(names), size
        root = ET.Element('mujoco', model='amdm_capsule_person')
        assets = ET.SubElement(root, 'asset')
        ET.SubElement(assets, 'texture', name='floor_checker', type='2d', builtin='checker',
                      rgb1='0.36 0.39 0.42', rgb2='0.52 0.55 0.58', width='512', height='512')
        ET.SubElement(assets, 'material', name='floor_material', texture='floor_checker',
                      texrepeat='1 1', texuniform='true', reflectance='0', shininess='0.1')
        add_shadow_settings(root)
        world = ET.SubElement(root, 'worldbody')
        ET.SubElement(world, 'light', name='body_light', pos='0 -3 5', dir='0 0.4 -1', directional='true')
        ET.SubElement(world, 'geom', name='ground', type='plane', size='500 500 0.1', material='floor_material')
        self.model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))
        self.data = mujoco.MjData(self.model)
        self.caps, self.boxes = [], []

    def set_pose(self, joints, rotations):
        """joints (22, 3) world LAFAN joint positions, rotations (22, 3, 3) global joint rotations (world)."""
        self.caps, self.boxes = shapes(np.asarray(joints), np.asarray(rotations), self.names, self.size)
        self.model.light_pos[0] = joints[0] + np.array([0., -3., 5.])  # keep the shadow volume on the character

    def draw(self, markers):
        for a, b, r in self.caps:
            if np.allclose(a, b):
                markers.geom(mujoco.mjtGeom.mjGEOM_SPHERE, (r, 0, 0), a, COLOR)
            else:
                g = markers.geom(mujoco.mjtGeom.mjGEOM_CAPSULE, (r, 0, 0), a, COLOR)
                if g is not None:
                    mujoco.mjv_connector(g, mujoco.mjtGeom.mjGEOM_CAPSULE, r, np.asarray(a, np.float64), np.asarray(b, np.float64))
        for centre, rot, full in self.boxes:
            markers.geom(mujoco.mjtGeom.mjGEOM_BOX, full / 2, centre, COLOR, rot)
