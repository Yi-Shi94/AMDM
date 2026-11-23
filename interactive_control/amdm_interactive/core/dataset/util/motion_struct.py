import numpy as np
from scipy.spatial.transform import Rotation as R

class Motion:
    def __init__(self, skeleton):
        self._skeleton = skeleton
        self._rotations = None
        self._positions = None
        self._orientations = None
        
        self._coord_rot_offset = np.eye(3)[None,...]
        self._fps = -1

    def trunc_motion_by_joint(self, joint_names):
        for name in joint_names:
            num_joint_dim = self._rotations.shape[1]
            dof_idx, joint_idx = self._skeleton.delete_joint(name)
            
            num_joint_dim = [i for i in range(num_joint_dim) if i not in joint_idx]
            self._rotations = self._rotations[:,num_joint_dim] 
            self._orientations = self._orientations[:, num_joint_dim]
            self._positions = self._positions[:, num_joint_dim]
    
    def zero_ground_plane(self, axis_idx=1):
        height = np.min(self._positions[:,:,axis_idx])
        self._positions[:,:,axis_idx] = self._positions[:,:,axis_idx] - height


    def translate_motion(self, offset_xy):
        self._positions[...,:,0] += offset_xy[0]
        self._positions[...,:,2] += offset_xy[1]
        

    def set_fps(self, fps):
        self._fps = fps

    def set_motion_frames(self, root_trans, rotations):
        self._rotations = rotations
        self._positions, self._orientations = self._skeleton.forward_kinematics(root_trans, rotations)


    def set_motion_to_rlforge(self, config):
        self.reset_default_pose(config["default_poses"])
        #dataset2isaacgym coordinate unit transform 
        self.reset_unit_scale(config["unit_transform"])
        #dataset2isaacgym coordinate sys transform (90 degree rot around x-axis)
        self.transform_coord_sys(config["coord_transform"])
    
    def restore_motion_from_rlforge(self, config):
        dataset2isaac_euler = config["coord_transform"]
        dataset2isaac_euler[1] *= -1
        
        self.transform_coord_sys(dataset2isaac_euler)
        self.reset_unit_scale(1/config["unit_transform"])

    def transform_coord_sys(self, euler_ang):
        self._coord_rot_offset = R.from_euler(euler_ang[0], euler_ang[1], degrees=True).as_matrix()[None,...]
        new_rotations = self._rotations
        new_rotations[...,0,:,:] = np.matmul(self._coord_rot_offset, new_rotations[...,0,:,:])
        self._rotations = new_rotations
        root_trans = np.matmul(self._coord_rot_offset,self._positions[...,0,:3,None]).squeeze()
        self._positions, self._orientations = self._skeleton.forward_kinematics(root_trans, new_rotations)

    def _insert_default_pose_in_first_frame(self):
        dof = np.zeros((1, self._skeleton._total_dof)) 
        positions, rotations, orientation = self._skeleton.forward_kinematics_from_pose(dof)
        self._positions = np.concatenate([positions, self._positions], axis=0)
        self._rotations = np.concatenate([rotations, self._rotations], axis=0)
        self._orientations = np.concatenate([orientation, self._orientations], axis=0)

    def reset_unit_scale(self, unit_scale):
        for i in range(len(self._skeleton._joint_lst)):
            self._skeleton._joint_lst[i]._offset *= unit_scale
        self._positions *= unit_scale
        root_trans = self._positions[...,0,:3]
        self._positions, self._orientations = self._skeleton.forward_kinematics(root_trans, self._rotations)

    def reset_default_pose(self, pose):
        new_default, _, Q_default2pose = self._skeleton.forward_kinematics_from_pose(pose)
        new_rotations = np.zeros_like(self._rotations)
        Q_default2pose_inv = Q_default2pose.transpose(0, 1, 3, 2)
        R_default = self._rotations

        for j in range(len(self._skeleton._joint_lst)):
            joint = self._skeleton._joint_lst[j]

            if joint._parent_idx is None:
                R_pose_cur = np.matmul(R_default[:,j], Q_default2pose_inv[:,j])
            else:
                temp = np.matmul(Q_default2pose[:,joint._parent_idx], R_default[:,j])
                R_pose_cur = np.matmul(temp, Q_default2pose_inv[:,j])
            new_rotations[:,j] = R_pose_cur

        root_trans = self._positions[...,0,:3]
        self._skeleton.set_default_offset(new_default)
        self._rotations = new_rotations
        self._positions, self._orientations = self._skeleton.forward_kinematics(root_trans, new_rotations)


class Skeleton:
    def __init__(self):
        self._joint_lst = []
        self._total_dof = 0
        self._root = None

    def set_root(self, joint):
        self._root = joint

    def add_joint(self, joint):
        self._joint_lst.append(joint)
        self._total_dof += joint._ndof
        
    def add_joints(self, joints):
        self._joint_lst.extend(joints)
        self._total_dof += sum([joint._ndof for joint in joints])


    def get_idx_joint_children_recur(self, joint):
        stack = [joint]
        child_lst = [joint]
        while len(stack)>0:
            children = [child for child in stack[-1]._child_joint_lst]
            if len(children) > 0:
                child_lst.extend(children)
                stack.extend(children)
            stack.pop(0)
        
        child_lst = [child._idx for child in child_lst]
        return child_lst
    
    def delete_joint(self, name_to_delete):
        idx_dof_to_delete = []
        recur_idx_to_delete = []
        accum_dof = 0
        for i in range(len(self._joint_lst)):
            
            if self._joint_lst[i]._name == name_to_delete:
                #print(name_to_delete, self._joint_lst[i]._name, self._joint_lst[i]._parent_idx)
                if self._joint_lst[i]._parent_idx is not None:
                    children_idx = self.get_idx_joint_children_recur(self._joint_lst[i])
                    recur_idx_to_delete.extend(children_idx)
                else:
                    for j in range(len(self._joint_lst[i]._child_joint_lst)):
                        self._joint_lst[i]._child_joint_lst[j]._parent_joint = None
                        self._joint_lst[i]._child_joint_lst[j]._parent_idx = None
                    recur_idx_to_delete.append(i)

        for joint in self._joint_lst:
            idx = joint._idx
            st = accum_dof
            ed = accum_dof + joint._ndof
            accum_dof += joint._ndof
            if idx in recur_idx_to_delete:
                idx_dof_to_delete.extend(list(range(st, ed)))

        self._joint_lst = [self._joint_lst[i] for i in range(len(self._joint_lst)) if i not in recur_idx_to_delete]

        for i, joint in enumerate(self._joint_lst):
            joint._idx = i
            parent_joint = joint._parent_joint
            joint._parent_idx = parent_joint._idx if parent_joint is not None else None
            joint._child_joint_lst = []

        for i, joint in enumerate(self._joint_lst):
            if joint._parent_idx is not None:
                self._joint_lst[i]._parent_joint._child_joint_lst.append(joint)

        self._joint_lst[0]._parent_idx = None
        self._joint_lst[0]._parent_joint = None
        return idx_dof_to_delete, recur_idx_to_delete


    def _build_body_children_map(self):
        num_joints = len(self._joint_lst)
        body_children = [[] for _ in range(num_joints)]
        for j in range(num_joints):
            parent_idx = self._joint_lst[j]._parent_idx
            if (parent_idx is not None):
                body_children[parent_idx].append(self._joint_lst[j])
        return body_children


    def set_default_offset(self, default_positions, is_global=True):
        for i in range(len(self._joint_lst)):
            if is_global:
                if self._joint_lst[i]._parent_idx is None:
                    parent_idx = i
                else:
                    parent_idx = self._joint_lst[i]._parent_idx
                offset = default_positions[...,i,:] - default_positions[...,parent_idx,:]
            else:
                offset = default_positions[...,i,:]
            self._joint_lst[i].set_offset(offset)


    def get_links(self, end_eff=True):
        links = []
        for i in range(len(self._joint_lst)):
            parent_joint_idx = self._joint_lst[i]._parent_idx
            dof = self._joint_lst[i]._ndof
            if not end_eff and dof == 0:
                continue

            if parent_joint_idx is not None:
                joint_idx = self._joint_lst[i]._idx
                links.append([joint_idx, parent_joint_idx])
        return links

    def get_joint_offset(self):
        joint_offset_lst = [jnt._offset for jnt in self._joint_lst]
        return np.array(joint_offset_lst)

    def get_joint_positions_default_pose(self):
        dof = np.zeros((1, self._total_dof))            
        return self.forward_kinematics_from_pose(dof)[0]

    def get_char_height(self):
        #only use after reset as tpose, isaac coord and meter
        #position_root = self._skeleton._root._offset()
        min_height = np.inf
        max_height = -np.inf

        positions_default = self.get_joint_positions_default_pose()
        for i in range(len(self._joint_lst)):
            joint_height = positions_default[0,i,2]
           
            if joint_height < min_height:
                min_height = joint_height
            if joint_height > max_height:
                max_height = joint_height
        
        root_height =  max_height - min_height
        return root_height

    def get_root_height(self):
        #only use after reset as tpose, isaac coord and meter
        positions_default = self.get_joint_positions_default_pose()
        min_height = np.inf
        for i in range(len(self._joint_lst)):
            joint_height = positions_default[0,i,2]
            if joint_height < min_height:
                min_height = joint_height
        root_height =  positions_default[0,0,2] - min_height
        return root_height

    def get_dof_joint_index(self):
        jnt_idx_lst = []
        for i in range(len(self._joint_lst)): 
            num_dof = self._joint_lst[i]._ndof
            if num_dof > 0:
                jnt_idx_lst.append(i)
        return jnt_idx_lst
    

    def get_dof_index(self):
        dof_idx_lst = []
        for i in range(len(self._joint_lst)): 
            num_dof = self._joint_lst[i]._ndof
            if self._joint_lst[i]._parent_idx is None:
                cur_idx = 0
            else:
                cur_idx = 3 + i * 3
            dof_idx_lst.extend([cur_idx + j for j in range(num_dof)])

        return dof_idx_lst


    def pose_to_dof(self, pose):
        dof_idx_lst = self.get_dof_index()
        dof = pose[..., dof_idx_lst]
        return dof

    def dof_to_pose(self, dof):
        b = 1 if len(dof.shape) == 1 else dof.shape[0]
        pose = np.zeros((b, 3*len(self._joint_lst)+3))
        dof_idx_lst = self.get_dof_index()
        pose[..., dof_idx_lst] = dof
        return pose        
    
    def forward_kinematics_from_pose(self, pose):
        if isinstance(pose, list):
            pose = np.array(pose)
        if len(pose.shape) == 1:
            pose = pose[None, ...]
        
        if pose.shape[-1] < len(self._joint_lst)*3+3:
            pose = self.dof_to_pose(pose)    
      
        root_trans = pose[..., :3]
        rotation_euler = pose[..., 3:].reshape(1, len(self._joint_lst), 3)
        rotations = np.zeros((rotation_euler.shape[0], len(self._joint_lst), 3, 3))
        
        for i in range(len(self._joint_lst)):
            rot_axis_order = self._joint_lst[i]._rot_axis_order
            if not rot_axis_order or len(rot_axis_order) == 0:
                 rot_axis_order = 'ZYX'
            rotations[:,i] = R.from_euler(rot_axis_order, rotation_euler[0,i], degrees=True).as_matrix()

        positions, orientations = self.forward_kinematics(root_trans, rotations)
        return positions, rotations, orientations


    def forward_kinematics(self, root_trans, rotations):       
        num_jnt = len(self._joint_lst)
        orientation_mats = np.zeros((rotations.shape[0], num_jnt, 3, 3))
        positions = np.zeros((rotations.shape[0], num_jnt, 3))
        
        for idx_jnt in range(num_jnt):
            joint = self._joint_lst[idx_jnt] 
            idx_parent_jnt = joint._parent_idx
            if idx_parent_jnt is None:
                orientation_mats[:, idx_jnt] = rotations[:, idx_jnt]
            else:                
                orientation_mats[:, idx_jnt] = np.matmul(orientation_mats[:, idx_parent_jnt], rotations[:, idx_jnt])
                positions[:,idx_jnt] = positions[:, idx_parent_jnt] + np.matmul(orientation_mats[:,idx_parent_jnt], joint._offset)
        
        positions += root_trans[:, None, :]
        return positions, orientation_mats


class Joint:
    def __init__(self, name, idx):
        self._name = name
        self._idx = idx
        self._parent_idx = None
        self._parent_joint = None
        self._offset = np.zeros(3) * 1.0

        self._ndof = 0
        self._child_joint_lst = []
        self._rot_axis_order = ''

    def add_parent(self, parent_joint):
        self._parent_joint = parent_joint
        if parent_joint:
            self._parent_joint._child_joint_lst.append(self)
            self._parent_idx = self._parent_joint._idx

    def add_child(self, child_joint):
        self._child_joint_lst.append(child_joint)

    def set_offset(self, coord):
        self._offset = coord.squeeze() * 1.0
        
    def set_dof(self, ndof):
        self._ndof = ndof
    
    def set_rot_axis_order(self, axis_order):
        self._rot_axis_order = axis_order


