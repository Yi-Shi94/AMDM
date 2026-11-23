"""Continuous SMPL skin and separate contact proxies for MuJoCo playback.

The neutral template's 24 skin weights deform its full surface in MuJoCo.
Capsules and endpoint spheres are separate collidable geoms, because MuJoCo
skins are visual only.
"""

from __future__ import annotations

from pathlib import Path
import os
import struct
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

# Fitted SMPL-H template written by amdm_interactive/fit_smpl_shape.py (the SMPL-H model itself is not redistributed).
SMPL_SOURCE = Path(os.environ.get(
    "AMDM_SMPL_SOURCE",
    str(Path(__file__).resolve().parents[1] / "body_models/smpl_lafan_fitted/SMPL_LAFAN_FITTED.npz"),
))
MESH_CACHE = SMPL_SOURCE.parent / "mesh_cache"
NAMES = (
    "root", "L_Hip", "R_Hip", "Torso", "L_Knee", "R_Knee", "Spine",
    "L_Ankle", "R_Ankle", "Chest", "L_Toe", "R_Toe", "Neck",
    "L_Thorax", "R_Thorax", "Head", "L_Shoulder", "R_Shoulder",
    "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist", "L_Hand", "R_Hand",
)
PARENTS = (-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19, 20, 21)
CHILD = (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, -1, -1, 15, 16, 17, -1, 18, 19, 20, 21, 22, 23, -1, -1)
RADII = (0.11, 0.075, 0.075, 0.095, 0.058, 0.058, 0.095, 0.05, 0.05,
         0.12, 0.045, 0.045, 0.045, 0.06, 0.06, 0.12, 0.055, 0.055,
         0.042, 0.042, 0.032, 0.032, 0.035, 0.035)
PRIMITIVE_LINK_RADII = {
    "Torso": 0.07, "Spine": 0.08, "Neck": 0.045,
    "L_Thorax": 0.045, "R_Thorax": 0.045,
    "L_Shoulder": 0.045, "R_Shoulder": 0.045,
    "L_Elbow": 0.04, "R_Elbow": 0.04,
    "L_Wrist": 0.032, "R_Wrist": 0.032,
    "L_Hip": 0.055, "R_Hip": 0.055,
    "L_Knee": 0.05, "R_Knee": 0.05,
    "L_Ankle": 0.045, "R_Ankle": 0.045,
}
PRIMITIVE_SPHERES = {
    "root": (0.09, (0.0, 0.0, 0.0)),
    "Chest": (0.13, (0.0, 0.0, 0.08)),
    "Head": (0.12, (0.0, 0.0, 0.09)),
    "L_Hand": (0.04, (0.0, 0.0, 0.0)),
    "R_Hand": (0.04, (0.0, 0.0, 0.0)),
    "L_Toe": (0.04, (0.0, 0.0, 0.0)),
    "R_Toe": (0.04, (0.0, 0.0, 0.0)),
}
# Exact rest joint positions of the local LAFAN BVH, converted from centimetre
# y-up offsets to metre z-up coordinates and ordered like NAMES.
PRIMITIVE_REST = np.array([
    [0.0, 0.0, 0.0], [-0.0068, 0.0695, -0.0914], [-0.0043, -0.0677, -0.0905],
    [-0.0267, -0.0025, 0.1090], [-0.0113, 0.1038, -0.4666],
    [-0.0132, -0.1060, -0.4731], [-0.0256, 0.0030, 0.2442],
    [-0.0550, 0.0902, -0.8646], [-0.0555, -0.0902, -0.8715],
    [-0.0002, 0.0045, 0.2971], [0.0643, 0.1166, -0.9204],
    [0.0678, -0.1156, -0.9196], [-0.0431, 0.0017, 0.5110],
    [-0.0343, 0.0833, 0.4188], [-0.0388, -0.0773, 0.4159],
    [0.0082, 0.0069, 0.5760], [-0.0432, 0.1743, 0.4493],
    [-0.0479, -0.1733, 0.4485], [-0.0707, 0.4339, 0.4365],
    [-0.0693, -0.4270, 0.4352], [-0.0719, 0.6831, 0.4455],
    [-0.0749, -0.6823, 0.4430], [-0.0868, 0.7671, 0.4373],
    [-0.0852, -0.7669, 0.4369],
], dtype=np.float64)


def _to_world(a: np.ndarray) -> np.ndarray:
    """SMPL y-up, x-left, z-forward to motion x-forward, y-left, z-up."""
    return a[..., [2, 0, 1]]


def _skin_file(source: Path, cache: Path) -> tuple[np.ndarray, Path]:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SMPL template missing: {source}; pass --smpl_source")
    with np.load(source) as d:
        rest = _to_world(d["J"][:24]).astype(np.float64)
        verts = _to_world(d["v_template"]).astype(np.float64)
        faces = d["f"].astype(np.int64)
        weights = d["weights_prior"].astype(np.float32)
    cache = Path(cache).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "smpl_neutral.skn"
    if not path.exists() or path.stat().st_mtime < source.stat().st_mtime:
        with path.open("wb") as out:
            out.write(struct.pack("<4i", len(verts), 0, len(faces), 24))
            out.write(verts.astype("<f4").tobytes())
            out.write(faces.astype("<i4").tobytes())
            for i, name in enumerate(NAMES):
                indices = np.flatnonzero(weights[:, i] > 1e-6).astype("<i4")
                out.write(f"smpl_{name}".encode().ljust(40, b"\0"))
                out.write(rest[i].astype("<f4").tobytes())
                out.write(np.array([1, 0, 0, 0], dtype="<f4").tobytes())
                out.write(struct.pack("<i", len(indices)))
                out.write(indices.tobytes())
                out.write(weights[indices, i].astype("<f4").tobytes())
    return rest, path


def _quat(rotation: Rotation) -> np.ndarray:
    q = rotation.as_quat()  # scipy xyzw -> MuJoCo wxyz
    return q[[3, 0, 1, 2]]


def _align(a: np.ndarray, b: np.ndarray) -> Rotation:
    a = a / max(np.linalg.norm(a), 1e-9)
    b = b / max(np.linalg.norm(b), 1e-9)
    cross = np.cross(a, b)
    q = np.r_[1 + np.dot(a, b), cross]
    if np.linalg.norm(q) < 1e-7:
        axis = np.cross(a, [0, 0, 1])
        if np.linalg.norm(axis) < 1e-7:
            axis = np.cross(a, [0, 1, 0])
        return Rotation.from_rotvec(np.pi * axis / np.linalg.norm(axis))
    q /= np.linalg.norm(q)
    return Rotation.from_quat(q[[1, 2, 3, 0]])



def add_shadow_settings(root):
    """Sharp shadows on the 500 m floor. The floor makes MuJoCo's scene extent 100 m and the directional light's
    shadow map is sized from it (shadowclip * extent), so by default one map covers ~200 m and the shadows come out
    as ~5 cm blocks. The light follows the character, so a ~5 m shadow box around it is enough."""
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "quality", shadowsize="8192")
    ET.SubElement(visual, "map", shadowclip="0.05")

class SMPLMujocoBody:
    """SMPL-shaped kinematic body with capsules usable in a MuJoCo scene.

    ``set_pose`` accepts world joint positions in ``NAMES`` order. The model
    and data are public so a tracking pipeline can add its own viewer/physics.
    """

    def __init__(self, source: Path = SMPL_SOURCE, mesh_cache: Path = MESH_CACHE,
                 *, visual: str = "primitives", collision: bool = True, extra_assets: str = "",
                 extra_worldbody: str = ""):
        if visual not in ("primitives", "skin", "collision"):
            raise ValueError("visual must be 'primitives', 'skin', or 'collision'")
        self.visual = visual
        collision_rgba = "0.25 0.58 0.85 1" if visual == "collision" else "0.2 0.6 0.9 0"
        collision_group = "0" if visual == "collision" else "3"
        if visual == "skin":
            self.rest, skin_path = _skin_file(source, mesh_cache)
        else:
            self.rest = PRIMITIVE_REST.copy()
        root = ET.Element("mujoco", model="amdm_smpl")
        ET.SubElement(root, "compiler", angle="radian")
        option = ET.SubElement(root, "option", timestep="0.02")
        option.set("gravity", "0 0 -9.81")
        assets = ET.SubElement(root, "asset")
        ET.SubElement(assets, "texture", name="floor_checker", type="2d", builtin="checker",
                      rgb1="0.36 0.39 0.42", rgb2="0.52 0.55 0.58", width="512", height="512")
        ET.SubElement(assets, "material", name="floor_material", texture="floor_checker",
                      texrepeat="1 1", texuniform="true", reflectance="0", shininess="0.1")
        if extra_assets:
            for element in ET.fromstring(f"<asset>{extra_assets}</asset>"):
                assets.append(element)
        if visual == "skin":
            deformable = ET.SubElement(root, "deformable")
            ET.SubElement(deformable, "skin", name="smpl_surface", file=str(skin_path),
                          rgba="0.78 0.61 0.48 1")
        add_shadow_settings(root)
        world = ET.SubElement(root, "worldbody")
        ET.SubElement(world, "light", name="body_light", pos="0 -3 5",
                      dir="0 0.4 -1", directional="true")
        ET.SubElement(world, "geom", name="ground", type="plane", size="500 500 0.1",
                      material="floor_material", contype="1", conaffinity="1")
        for i, name in enumerate(NAMES):
            body = ET.SubElement(world, "body", name=f"smpl_{name}", mocap="true")
            if visual == "primitives":
                if name in PRIMITIVE_SPHERES:
                    radius, pos = PRIMITIVE_SPHERES[name]
                    ET.SubElement(body, "geom", name=f"visual_sphere_{name}", type="sphere",
                                  pos=" ".join(map(str, pos)), size=str(radius),
                                  rgba="0.75 0.56 0.43 1", contype="0", conaffinity="0")
            if collision and CHILD[i] < 0:
                ET.SubElement(body, "geom", name=f"collision_{name}", type="sphere",
                              pos="0 0 0.09" if name == "Head" else "0 0 0",
                              size=str(RADII[i]), rgba=collision_rgba,
                              contype="1", conaffinity="1", group=collision_group)
            if CHILD[i] >= 0:
                segment = ET.SubElement(world, "body", name=f"segment_{name}", mocap="true")
                if visual == "primitives" and name in PRIMITIVE_LINK_RADII:
                    ET.SubElement(segment, "geom", name=f"visual_link_{name}", type="capsule",
                                  size=f"{PRIMITIVE_LINK_RADII[name]} 0.05",
                                  rgba="0.75 0.56 0.43 1", contype="0", conaffinity="0")
                if collision:
                    ET.SubElement(segment, "geom", name=f"collision_{name}", type="capsule",
                                  size=f"{RADII[i]} 0.05", rgba=collision_rgba,
                                  contype="1", conaffinity="1", group=collision_group)
        if extra_worldbody:
            for element in ET.fromstring(f"<worldbody>{extra_worldbody}</worldbody>"):
                world.append(element)
        self.model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        self.data = mujoco.MjData(self.model)
        self.body_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"smpl_{n}") for n in NAMES]
        self.segment_body_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY,
                                                  f"segment_{n}") if CHILD[i] >= 0 else -1
                                 for i, n in enumerate(NAMES)]
        self.collision_ids = ([mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM,
                                                f"collision_{n}") for n in NAMES] if collision else [])
        self.visual_link_ids = ([mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM,
                                                 f"visual_link_{n}") if n in PRIMITIVE_LINK_RADII else -1
                                 for n in NAMES] if visual == "primitives" else [])
        self.collision = collision

    def set_collision_display(self, enabled: bool) -> None:
        """Switch a skin body between mesh and collision proxies in-place."""
        if self.visual != "skin" or not self.collision:
            raise ValueError("display switching requires visual='skin', collision=True")
        self.model.skin_rgba[:, 3] = 0.0 if enabled else 1.0
        self.model.geom_rgba[self.collision_ids] = [0.25, 0.58, 0.85, 1.0 if enabled else 0.0]
        self.model.geom_group[self.collision_ids] = 0 if enabled else 3

    def set_pose(self, joints: np.ndarray, rotations: np.ndarray | None = None) -> None:
        joints = np.asarray(joints, dtype=np.float64)
        if joints.shape != (24, 3) or not np.isfinite(joints).all():
            raise ValueError("expected 24 finite world joint positions in SMPL order")
        joints = joints.copy()
        # 100STYLE has wrist tracks but no distinct hand joint. Its prepared
        # cache duplicates wrist at hand; extrapolate the palm so the SMPL
        # wrist/hand skin does not collapse into a zero-length bone.
        for elbow, wrist, hand in ((18, 20, 22), (19, 21, 23)):
            if np.linalg.norm(joints[hand] - joints[wrist]) < 1e-4:
                forearm = joints[wrist] - joints[elbow]
                norm = np.linalg.norm(forearm)
                if norm > 1e-6:
                    joints[hand] = joints[wrist] + 0.085 * forearm / norm
        if rotations is not None:
            matrices = np.asarray(rotations, dtype=np.float64)
            if matrices.shape != (24, 3, 3) or not np.isfinite(matrices).all():
                raise ValueError("expected 24 finite world rotation matrices")
            body_rotations = Rotation.from_matrix(matrices)
        else:
            # Legacy position-only frames determine swing but leave twist
            # ambiguous. Rotation-aware frames use the BVH orientations above.
            rest_axes = np.stack([self.rest[k] - self.rest[0] for k in (1, 2, 3)])
            pose_axes = np.stack([joints[k] - joints[0] for k in (1, 2, 3)])
            root_rot, _ = Rotation.align_vectors(pose_axes, rest_axes)
            estimated = [root_rot]
            for i in range(1, 24):
                parent = PARENTS[i]
                child = CHILD[i]
                if i == 9:
                    anchors = (12, 13, 14)
                    pose_axes = np.stack([joints[k] - joints[i] for k in anchors])
                    rest_axes = np.stack([self.rest[k] - self.rest[i] for k in anchors])
                    rotation, _ = Rotation.align_vectors(pose_axes, rest_axes)
                elif child >= 0 and np.linalg.norm(joints[child] - joints[i]) > 1e-5:
                    current = joints[child] - joints[i]
                    inherited = estimated[parent]
                    expected = inherited.apply(self.rest[child] - self.rest[i])
                    rotation = _align(expected, current) * inherited
                else:
                    rotation = estimated[parent]
                estimated.append(rotation)
            body_rotations = Rotation.from_quat(np.stack([r.as_quat() for r in estimated]))
        for i, bid in enumerate(self.body_ids):
            mid = self.model.body_mocapid[bid]
            self.data.mocap_pos[mid] = joints[i]
            self.data.mocap_quat[mid] = _quat(body_rotations[i])
            if CHILD[i] >= 0 and (self.collision or self.visual == "primitives"):
                start, end = joints[i], joints[CHILD[i]]
                target = end - start
                length = max(float(np.linalg.norm(target)), 1e-6)
                segment_mocap = self.model.body_mocapid[self.segment_body_ids[i]]
                self.data.mocap_pos[segment_mocap] = (start + end) / 2
                self.data.mocap_quat[segment_mocap] = _quat(_align(np.array([0, 0, 1.0]),
                                                                 target / length))
                geom_ids = []
                if self.collision:
                    geom_ids.append(self.collision_ids[i])
                if self.visual_link_ids and self.visual_link_ids[i] >= 0:
                    geom_ids.append(self.visual_link_ids[i])
                for gid in geom_ids:
                    self.model.geom_size[gid, 1] = length / 2
        # Keep the finite directional-light shadow volume near the character
        # during indefinitely long world-space rollouts.
        self.model.light_pos[0] = joints[0] + np.array([0., -3., 5.])
        self.model.stat.center[:] = joints[0]
        ground = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        # Two-metre shifts preserve checker phase (one texture repeat).
        self.model.geom_pos[ground, :2] = np.floor(joints[0, :2] / 2.) * 2.
        mujoco.mj_forward(self.model, self.data)

    def contact_names(self) -> list[tuple[str, str]]:
        """Return current MuJoCo contact pairs (including ground contact)."""
        return [(self.model.geom(i.geom1).name, self.model.geom(i.geom2).name)
                for i in self.data.contact]
