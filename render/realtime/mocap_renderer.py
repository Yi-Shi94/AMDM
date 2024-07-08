import os
import sys
import itertools

import torch
import torch.nn.functional as F
import numpy as np

import matplotlib.cm as mpl_color
from imageio import imwrite

import pybullet as pb
from policy.common.bullet_objects import VSphere, VCylinder, VCapsule, FlagPole, Arrow
from policy.common.bullet_utils import BulletClient, Camera, SinglePlayerStadiumScene

FOOT2METER = 1.3
DEG2RAD = np.pi / 180
FADED_ALPHA = 1.0

def extract_joints_xyz(xyzs):
    x = xyzs[...,0]
    y = xyzs[...,1]
    z = xyzs[...,2]
    return x, y, z


class PBLMocapViewer:
    def __init__(
        self,
        env,
        num_characters=1,
        use_params=True,
        target_fps = 0,
        camera_tracking=True,
    ):
        self.device = env.device
        target_fps = env.dataset.fps
        sk_dict = env.sk_dict
        sk_dict['links'] = env.dataset.links

        self.env = env
        self.num_characters = num_characters
        self.use_params = use_params

        
        self.character_index = 0
        self.controller_autonomy = 1.0
        self.debug = False
        self.gui = False

        #==================
        self.camera_tracking = camera_tracking
        # use 1.5 for close up, 3 for normal, 6 with GUI
        self.camera_distance = 6 if self.camera_tracking else 12
        self.camera_smooth = np.array([1, 1, 1])

        connection_mode = pb.GUI if env.is_rendered else pb.DIRECT
        self._p = BulletClient(connection_mode=connection_mode)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_GUI, 0)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_KEYBOARD_SHORTCUTS, 0)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_MOUSE_PICKING, 0)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_SEGMENTATION_MARK_PREVIEW, 0)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_DEPTH_BUFFER_PREVIEW, 0)
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RGB_BUFFER_PREVIEW, 0)

        # Disable rendering during creation
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 0)

        self.camera = Camera(
            self._p, fps=target_fps, dist=self.camera_distance, pitch=-10, yaw=45
        )
        scene = SinglePlayerStadiumScene(
            self._p, gravity=9.8, timestep=1 / target_fps, frame_skip=1
        )
        scene.initialize()

        cmap = mpl_color.get_cmap("coolwarm")
        self.colours = cmap(np.linspace(0, 1, self.num_characters))

        if num_characters == 1:
            self.colours[0] = (0.98, 0.54, 0.20, 1)

        # here order is important for some reason ?
        # self.targets = MultiTargets(self._p, num_characters, self.colours)
        self.characters = MultiMocapCharacters(self._p, num_characters,  sk_dict, self.colours)
        
        # Re-enable rendering
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 1)

        self.state_id = self._p.saveState()

        if self.use_params:
            self._setup_debug_parameters()

    def reset(self):
        # self._p.restoreState(self.state_id)
        self.env.reset()
    
    def add_path_markers(self, path):
        if not hasattr(self, "path"):
            num_points = min(100, len(path))
            colours = np.tile([1, 1, 1, 0.5], [num_points, 1])
            self.path = MultiTargets(self._p, num_points, colours)
        else:
            num_points =  min(100, len(path))
        #num_points = min(100, len(path))
        indices = torch.linspace(0, len(path) - 1, num_points).long()
        positions = F.pad(path[indices] * FOOT2METER, pad=[0, 1], value=0)
        for index, position in enumerate(positions.cpu().numpy()):
            self.path.set_position(position, index)
    

    def update_target_markers(self, targets):
        #from environments.mocap_envs import JoystickEnv
       
        
        render_arrow = True if self.env.NAME == 'JOYSTICK' else False
        if not hasattr(self, "targets"):
            marker = Arrow if render_arrow else FlagPole
            self.targets = MultiTargets(
                self._p, self.num_characters, self.colours, marker
            )
            
            #data = self.poses[np.random.randint(self.poses.shape[0])]
            #self.targets = MocapCharacterTarget(
            #    self._p, self.num_characters, data, self.colours, None
            #)

        if render_arrow:
            target_xyzs = F.pad(self.env.root_xz, pad=[0, 1]) * FOOT2METER
            target_orns = self.env.target_direction_buf
            
            for index, (pos, angle) in enumerate(zip(target_xyzs, target_orns)):
                orn = self._p.getQuaternionFromEuler([0, 0, -(float(angle)-np.pi/2)])
                self.targets.set_position(pos, index, orn)
        else:
            if targets.shape[-1] == 2:
                targets = F.pad(targets, pad=[0, 1], value=0)
            target_xyzs = (
                ( targets * FOOT2METER).cpu().numpy()
            )
        
            for index in range(self.num_characters):
                self.targets.set_position(target_xyzs[index], index)
                #height = target_xyzs[:,1]


    def duplicate_character(self):
        characters = self.characters
        colours = self.colours
        num_characters = self.num_characters
        bc = self._p

        bc.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 0)

        if self.characters.has_links:
            for index, colour in zip(range(num_characters), colours):
                faded_colour = colour.copy()
                faded_colour[-1] = FADED_ALPHA
                characters.heads[index].set_color(faded_colour)
                characters.links[index] = []

        self.characters = MultiMocapCharacters(bc, num_characters, self.env.sk_dict, colours)
    
        if hasattr(self, "targets") and self.targets.marker == Arrow:
            self.targets = MultiTargets(
                self._p, self.num_characters, self.colours, Arrow
            )

        bc.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 1)

    def render(self, xyzs, facings, root_xzs, time_remain, action):
        x, z, y = extract_joints_xyz(xyzs)
        num_jnt = x.shape[-1]
        
        mat = self.env.get_rotation_matrix(facings).to(self.device)

        rotated_xy = torch.matmul(mat[...,None,:,:].expand(-1,num_jnt,-1,-1), torch.stack((x, y), dim=-1)[...,None])[...,0]
        #rotated_xy *= 0
        
        poses = torch.cat((rotated_xy, z[...,None]), dim=-1).permute(0, 2, 1)
        root_xyzs = F.pad(root_xzs, pad=[0, 1])
        #root_xyzs *= 0
        joint_xyzs = ((poses + root_xyzs.unsqueeze(dim=-1)) * FOOT2METER).cpu().numpy()
        self.root_xyzs = (
            (F.pad(root_xzs, pad=[0, 1], value=3) * FOOT2METER).cpu().numpy()
        )
        self.joint_xyzs = joint_xyzs

        for index in range(self.num_characters):
            self.characters.set_joint_positions(joint_xyzs[index], index)

            if self.debug and index == self.character_index:
                target_dist = (
                    -float(self.env.linear_potential[index])
                    if hasattr(self.env, "linear_potential")
                    else 0
                )
                print(
                    "FPS: {:4.1f} | Time Left: {:4.1f} | Distance: {:4.1f} ".format(
                        self.camera._fps, float(time_remain), target_dist
                    )
                )
                if action is not None:
                    a = action[index]
                    print(
                        "max: {:4.2f} | mean: {:4.2f} | median: {:4.2f} | min: {:4.2f}".format(
                            float(a.max()),
                            float(a.mean()),
                            float(a.median()),
                            float(a.min()),
                        )
                    )

        self._handle_mouse_press()
        self._handle_key_press()
        if self.use_params:
            self._handle_parameter_update()
        if self.camera_tracking:
            self.camera.track(self.root_xyzs[self.character_index], self.camera_smooth)
        else:
            self.camera.wait()

    def close(self):
        self._p.disconnect()
        sys.exit(0)

    def _setup_debug_parameters(self):
        max_frame = self.env.max_timestep - self.env.num_condition_frames
        self.parameters = [
            {
                # -1 for random start frame
                "default": -1,
                "args": ("Start Frame", -1, max_frame, -1),
                "dest": (self.env, "debug_frame_index"),
                "func": lambda x: int(x),
                "post": lambda: self.env.reset(),
            },
            {
                "default": self.env.data_fps,
                "args": ("Target FPS", 1, 240, self.env.data_fps),
                "dest": (self.camera, "_target_period"),
                "func": lambda x: 1 / (x + 1),
            },
            {
                "default": 1,
                "args": ("Controller Autonomy", 0, 1, 1),
                "dest": (self, "controller_autonomy"),
                "func": lambda x: x,
            },
            {
                "default": 1,
                "args": ("Camera Track Character", 0, 1, int(self.camera_tracking)),
                "dest": (self, "camera_tracking"),
                "func": lambda x: x > 0.5,
            },
        ]

        if self.num_characters > 1:
            self.parameters.append(
                {
                    "default": 1,
                    "args": ("Selected Character", 1, self.num_characters + 0.999, 1),
                    "dest": (self, "character_index"),
                    "func": lambda x: int(x - 1.001),
                }
            )

        max_frame_skip = 1#self.env.num_future_predictions
        if max_frame_skip > 1:
            self.parameters.append(
                {
                    "default": 1,
                    "args": (
                        "Frame Skip",
                        1,
                        max_frame_skip + 0.999,
                        self.env.frame_skip,
                    ),
                    "dest": (self.env, "frame_skip"),
                    "func": lambda x: int(x),
                }
            )

        if hasattr(self.env, "target_direction"):
            self.parameters.append(
                {
                    "default": 0,
                    "args": ("Target Direction", 0, 359, 0),
                    "dest": (self.env, "target_direction"),
                    "func": lambda x: x / 180 * np.pi,
                    "post": lambda: self.env.reset_target(),
                }
            )

        if hasattr(self.env, "target_speed"):
            self.parameters.append(
                {
                    "default": 0,
                    "args": ("Target Speed", 0.0, 0.8, 0.5),
                    "dest": (self.env, "target_speed"),
                    "func": lambda x: x,
                }
            )

        # setup Pybullet parameters
        for param in self.parameters:
            param["id"] = self._p.addUserDebugParameter(*param["args"])

    def _handle_parameter_update(self):
        for param in self.parameters:
            func = param["func"]
            value = func(self._p.readUserDebugParameter(param["id"]))
            cur_value = getattr(*param["dest"], param["default"])
            if cur_value != value:
                setattr(*param["dest"], value)
                if "post" in param:
                    post_func = param["post"]
                    post_func()

    def _handle_mouse_press(self):
        events = self._p.getMouseEvents()
        for ev in events:
            if ev[0] == 2 and ev[3] == 0 and ev[4] == self._p.KEY_WAS_RELEASED:
                # (is mouse click) and (is left click)

                width, height, _, proj, _, _, _, _, yaw, pitch, dist, target = (
                    self._p.getDebugVisualizerCamera()
                )

                pitch *= DEG2RAD
                yaw *= DEG2RAD

                R = np.reshape(
                    self._p.getMatrixFromQuaternion(
                        self._p.getQuaternionFromEuler([pitch, 0, yaw])
                    ),
                    (3, 3),
                )

                # Can't use the ones returned by pybullet API, because they are wrong
                camera_up = np.matmul(R, [0, 0, 1])
                camera_forward = np.matmul(R, [0, 1, 0])
                camera_right = np.matmul(R, [1, 0, 0])

                x = ev[1] / width
                y = ev[2] / height

                # calculate from field of view, which should be constant 90 degrees
                # can also get from projection matrix
                # d = 1 / np.tan(np.pi / 2 / 2)
                d = proj[5]

                A = target - camera_forward * dist
                aspect = height / width

                B = (
                    A
                    + camera_forward * d
                    + (x - 0.5) * 2 * camera_right / aspect
                    - (y - 0.5) * 2 * camera_up
                )

                C = (
                    np.array(
                        [
                            (B[2] * A[0] - A[2] * B[0]) / (B[2] - A[2]),
                            (B[2] * A[1] - A[2] * B[1]) / (B[2] - A[2]),
                            0,
                        ]
                    )
                    / FOOT2METER
                )

                if hasattr(self.env, "reset_target"):
                    self.env.reset_target(location=C)

    def _handle_key_press(self, keys=None):
        if keys is None:
            keys = self._p.getKeyboardEvents()
        RELEASED = self._p.KEY_WAS_RELEASED

        # keys is a dict, so need to check key exists
        if keys.get(ord("d")) == RELEASED:
            self.debug = not self.debug
        elif keys.get(ord("g")) == RELEASED:
            self.gui = not self.gui
            self._p.configureDebugVisualizer(pb.COV_ENABLE_GUI, int(self.gui))
        elif keys.get(ord("n")) == RELEASED:
            # doesn't work with pybullet's UserParameter
            self.character_index = (self.character_index + 1) % self.num_characters
            self.camera.lookat(self.root_xyzs[self.character_index])
        elif keys.get(ord("m")) == RELEASED:
            self.camera_tracking = not self.camera_tracking
        elif keys.get(ord("q")) == RELEASED:
            self.close()
        elif keys.get(ord("r")) == RELEASED:
            self.reset()
        elif keys.get(ord("t")) == RELEASED:
            self.env.reset_target()
        elif keys.get(ord("i")) == RELEASED:
            image = self.camera.dump_rgb_array()
            imwrite("image_c.png", image)
        elif keys.get(ord("a")) == RELEASED:
            image = self.camera.dump_orthographic_rgb_array()
            imwrite("image_o.png", image)
        elif keys.get(ord("v")) == RELEASED:
            import datetime

            now_string = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            filename = "{}.mp4".format(now_string)

            self._p.startStateLogging(self._p.STATE_LOGGING_VIDEO_MP4, filename)
        elif keys.get(ord(" ")) == RELEASED:
            while True:
                keys = self._p.getKeyboardEvents()
                if keys.get(ord(" ")) == RELEASED:
                    break
                elif keys.get(ord("a")) == RELEASED or keys.get(ord("i")) == RELEASED:
                    self._handle_key_press(keys)


class MultiMocapCharacters:
    def __init__(self, bc, num_characters, sk_dict, colours=None, links=True):
        self._p = bc
        self.has_links = links

        #self.dir_link  = 
        #            VCapsule(self._p, radius=0.06, height=0.1, rgba=colours[i])
        #            for i in range(num_characters)
        
        if links:
            self.linked_joints = np.array(sk_dict['links'])
            
            self.head_idx =  sk_dict['head_idx']
            self.num_joint =   sk_dict['num_joint']

            total_parts = num_characters * self.num_joint
            joints = VSphere(bc, radius=0.07, max=True, replica=total_parts)
            self.ids = joints.ids
            self.links = {
                i: [
                    VCapsule(self._p, radius=0.03, height=0.1, rgba=colours[i])
                    for _ in range(self.linked_joints.shape[0])
                ]
                for i in range(num_characters)
            }
            self.z_axes = np.zeros((self.linked_joints.shape[0], 3))
            self.z_axes[:, 2] = 1

            self.heads = [VSphere(bc, radius=0.12) for _ in range(num_characters)]

        if colours is not None:
            self.colours = colours
            for index, colour in zip(range(num_characters), colours):
                colour[3] = 1
                self.set_colour(colour, index)
                if links:
                    self.heads[index].set_color(colour)


    def set_colour(self, colour, index):
        # start = self.start_index + index * self.num_joints
        start = index * self.num_joint
        joint_ids = self.ids[start : start + self.num_joint]
        for id in joint_ids:
            self._p.changeVisualShape(id, -1, rgbaColor=colour)

    def set_joint_positions(self, xyzs, index):
        
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 0)

        start = index * self.num_joint
        joint_ids = self.ids[start : start + self.num_joint]
        
        xyzs = xyzs.transpose()
        for i, id in enumerate(joint_ids):
            self._p.resetBasePositionAndOrientation(id, posObj=xyzs[i], ornObj=(0, 0, 0, 1))

        
        if self.has_links:
            rgba = self.colours[index].copy()
            rgba[-1] = FADED_ALPHA
            deltas = xyzs[self.linked_joints[:, 1]] - xyzs[self.linked_joints[:, 0]]
            heights = np.linalg.norm(deltas, axis=-1)
            positions = xyzs[self.linked_joints].mean(axis=1)

            a = np.cross(deltas, self.z_axes)
            b = np.linalg.norm(deltas, axis=-1) + (deltas * self.z_axes).sum(-1)
            orientations = np.concatenate((a, b[:, None]), axis=-1)
            orientations[:, [0, 1]] *= -1

            for lid, (delta, height, pos, orn, link) in enumerate(
                zip(deltas, heights, positions, orientations, self.links[index])
            ):
                # 0.05 feet is about 1.5 cm
                if abs(link.height - height) > 0.05:
                    self._p.removeBody(link.id[0])
                    link = VCapsule(self._p, radius=0.06, height=height, rgba=rgba)
                    self.links[index][lid] = link

                link.set_position(pos, orn)

            self.heads[index].set_position(0.5 * (xyzs[self.head_idx[1]] - xyzs[self.head_idx[0]]) + xyzs[self.head_idx[1]])
            #self.dir_link.set_position 
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 1)


class MultiTargets:
    def __init__(self, bc, num_characters, colours=None, obj_class=VSphere):
        self._p = bc
        self.marker = obj_class

        # self.start_index = self._p.getNumBodies()
        flags = obj_class(self._p, replica=num_characters)
        self.ids = flags.ids

        if colours is not None:
            for index, colour in zip(range(num_characters), colours):
                #print(index, colour,'sad')
                if index == 0:
                    colour = [1,0,0,1]
                self.set_colour(colour, index)
        
        
        self.target_gnd = VSphere(self._p, radius=0.1, rgba=(1,0,0), max=True, replica=1)
        self.target_ed = VSphere(self._p, radius=0.04, rgba=(1.0,0.0,0.0), max=True, replica=10)

    def set_colour(self, colour, index):
        self._p.changeVisualShape(self.ids[index], -1, rgbaColor=(colour[0],colour[1],colour[2],1))

    def set_position(self, xyz, index, orn=(1, 0, 0, 1)):
        xyz = xyz[:3]
        self._p.resetBasePositionAndOrientation(self.ids[index], posObj=xyz, ornObj=orn)
        
        num_sph = int(xyz[2]/0.2)
        xyz[2] = 0.0
        self._p.resetBasePositionAndOrientation(self.target_gnd.ids[0], posObj=xyz, ornObj=orn)
        
        for i in range(10):
            pos = xyz
            if i > num_sph:
                pos[2] = num_sph * 0.2
            else:
                pos[2] = i * 0.2
            self._p.resetBasePositionAndOrientation(self.target_ed.ids[i], posObj=pos, ornObj=orn)


class MocapCharacter:
    def __init__(self, bc, rgba=None):

        self._p = bc
        num_joints = self._p.num_joint

        # useMaximalCoordinates=True is faster for things that don't `move`
        body = VSphere(bc, radius=0.07, rgba=rgba, max=True, replica=num_joints)
        self.joint_ids = body.ids

    def set_joint_positions(self, xyzs):
        for xyz, id in zip(xyzs, self.joint_ids):
            self._p.resetBasePositionAndOrientation(id, posObj=xyz, ornObj=(0, 0, 0, 1))


class MocapCharacterTarget:
    def __init__(self, bc, num_characters, body_data = None, colours=None, obj_class=None):
        assert body_data is not None
        self._p = bc
        num_joints = self._p.num_joint

        # useMaximalCoordinates=True is faster for things that don't `move`
        body = VSphere(bc, radius=0.07, rgba=colours[0], max=True, replica=num_joints*num_characters)
        self.joint_ids = body.ids
        self.joints = body_data
        self.num_joints = num_joints


        self.links = {
            i: [
                VCapsule(self._p, radius=0.06, height=0.1, rgba=colours[i])
                for _ in range(self.linked_joints.shape[0])
            ]
            for i in range(num_characters)
        }
        self.z_axes = np.zeros((self.linked_joints.shape[0], 3))
        self.z_axes[:, 2] = 1

        self.heads = [VSphere(bc, radius=0.12) for _ in range(num_characters)]

        if colours is not None:
            self.colours = colours
            for index, colour in zip(range(num_characters), colours):
                self.set_colour(colour, index)
                self.heads[index].set_color(colour)


    def set_colour(self, colour, index):
        # start = self.start_index + index * self.num_joints
        start = index * self.num_joints
        joint_ids = self.joint_ids[start : start + self.num_joints]
        for id in joint_ids:
            self._p.changeVisualShape(id, -1, rgbaColor=colour)


    def set_position(self, xyz, index, orn=(1, 0, 0, 1)):
        #xyz[2] = 0
        self.joints = self.joints + xyz[:3]
        self.set_joint_positions(self.joints,index)
    
    def set_joint_positions(self, xyzs, index):
        self._p.configureDebugVisualizer(pb.COV_ENABLE_RENDERING, 0)


        start = index * self.num_joints
        joint_ids = self.joint_ids[start : start + self.num_joints]
        for xyz, id in zip(xyzs, joint_ids):
            self._p.resetBasePositionAndOrientation(id, posObj=xyz, ornObj=(0, 0, 0, 1))

    