
import policy.envs.base_env as base_env
from render.realtime.mocap_renderer import PBLMocapViewer
import os.path as osp
import math
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym

from multiprocessing import Process
from filelock import FileLock
import dataset.util.geo as geo_util

user_input_lockfile = "miscs/interact_temp/user_text"

def record_text_to_temp(texts):
    lock = FileLock(user_input_lockfile + ".lock")
    with lock:
        file = open(user_input_lockfile, "w")
        file.write(texts)
        file.close()
    return

class TextBoxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Text Box GUI")

        self.text_var = tk.StringVar()
        self.text_entry = tk.Entry(self.root, textvariable=self.text_var)
        self.text_entry.pack(pady=10)

        self.submit_button = tk.Button(self.root, text="Submit", command=self.process_input)
        self.submit_button.pack()

        self.recorded_text = ''
        self.result_label = tk.Label(self.root, text="")
        self.result_label.pack()


    def process_input(self):
        # Process the input when the Submit button is clicked
        user_input = self.text_var.get()
        if user_input:
            result = f"You submitted: {user_input}"
            self.recorded_text = user_input
            record_text_to_temp(self.recorded_text)
            self.result_label.config(text=result)

            # Clear the text box after processing the input
            self.text_var.set("")

def start_gui():
    root = tk.Tk()
    app = TextBoxGUI(root)
    root.mainloop()


class InpaintEnv(base_env.EnvBase):
    NAME = "Inpaint"
    def __init__(self, config, model, dataset, device):      
        super().__init__(config, model, dataset, device)

        self.device = device
        self.config = config
        self.model = model
        self.dataset = dataset
        self.action = None
        self.links = self.dataset.links
        self.valid_idx = self.dataset.valid_idx

        self.interative_text = False
        self.stopsteps  = None
        self.cur_extra_info = {'repaint_step':config['edit']['repaint_step'],
                               'interact_stop_step':config['edit']['interact_stop_step']}
        self.updated_text = False

        if 'text' in config:
            self.interative_text = True
            self.texts = config['text']
            #assert len(self.texts) == self.num_parallel
            record_text_to_temp(';'.join(self.texts))
            self.gui_process = Process(target=start_gui)
            self.gui_process.start()
            #self.textbox = TextBox()
        else:
            self.texts = []
        self.update_textemb(self.texts)
        
        self.p_control = False
        self.waypoints = None
        self.waypoint_heading = None

        self.max_timestep = self.config['max_timestep']#3000
        self.action_dim = self.frame_dim
        self.timestep = 0
        self.substep = 0

        self.pre_init_data = None
        self.mask, self.content = self.process_edit_config(config)
        if self.waypoints is not None:
            waypoints = self.waypoints if len(self.waypoints.shape)==2 else self.waypoints[0]
            self.viewer.add_path_markers(waypoints)

            #path = waypoints * 0
            #radius = 2
            #theta = np.linspace(0, 2*np.pi, self.max_timestep)
            #x = radius * np.cos(theta) - radius 
            #y = radius * np.sin(theta)
            #path[...,0] = torch.from_numpy(x).to(self.device)
            #path[...,1] = torch.from_numpy(y).to(self.device)
            
            #self.viewer.add_path_markers(path)


        self.base_action = torch.zeros((self.num_parallel, 1, self.action_dim)).to(
            self.device
        )
        
        high = np.inf * np.ones([self.action_dim])
        self.action_space = gym.spaces.Box(-high, high, dtype=np.float32)

        self.observation_dim = (
            self.frame_dim * self.num_condition_frames + self.action_dim
        )

        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)


    def process_edit_config(self, config):
        
        #full_dim_lst = torch.zeros((self.num_parallel, self.max_timestep, self.frame_dim))
        mask = torch.zeros((self.num_parallel, self.max_timestep, self.frame_dim)).to(self.device)
        content = torch.zeros((self.num_parallel, self.max_timestep, self.frame_dim)).to(self.device)
        
        if 'edit' not in config:
            return mask, content
        
        edit_dict = config['edit']

        if 'full' in edit_dict:
            full_config = edit_dict['full']
            self.cur_target = 0
            self.st_frame_dict = {}
            self.ed_frame_dict = {}
            for num in full_config:   
               
                cur_full_config = full_config[num]
                data_start_frame = cur_full_config['data_start_frame']
                data_end_frame = cur_full_config['data_end_frame']
                start_frame = cur_full_config['start_frame']
                end_frame = cur_full_config['end_frame']
                if 'interact_stop_step' in cur_full_config:
                    if self.stopsteps is None:
                        self.stopsteps = torch.zeros((self.num_parallel, self.max_timestep))
                    self.stopsteps[:, start_frame:end_frame] = cur_full_config['interact_stop_step']
                self.st_frame_dict[int(num)] = start_frame
                self.ed_frame_dict[int(num)] = end_frame
                
                assert data_end_frame - data_start_frame == end_frame - start_frame

                dim_lst = list(range(0, self.dataset.frame_dim))
                #dim_lst = list(range(self.dataset.angle_dim_lst[0], self.dataset.angle_dim_lst[1]))
                #dim_lst = [0, self.dataset.height_index] #list(range(start_dim, end_dim)) #[0,1,2,self.dataset.height_index]
                
                file_name = cur_full_config['val']
                data = self.dataset.load_new_data(file_name)
                #self.pre_init_data = torch.tensor(data[None,data_start_frame-1]).to(self.device)
                data = self.dataset.denorm_data(data[data_start_frame:data_end_frame])
                data_trajs = self.dataset.x_to_trajs(data)
                self.waypoints = torch.tensor(data_trajs).to(self.device).float()
                
                data = torch.tensor(data).to(self.device).float()
                
                content[:, start_frame:end_frame, dim_lst] = data[None,:,dim_lst]
                mask[:, start_frame:end_frame, dim_lst] = 1
                

        elif 'full_trajectory' in edit_dict:
            data_start_frame = edit_dict['full_trajectory']['data_start_frame']
            data_end_frame = edit_dict['full_trajectory']['data_end_frame']
            start_frame = edit_dict['full_trajectory']['start_frame']
            end_frame = edit_dict['full_trajectory']['end_frame']

            assert data_end_frame - data_start_frame == end_frame-start_frame
          
            dim_lst = self.dataset.get_dim_by_key('heading',None)
        
        
            file_name = edit_dict['full_trajectory']['val']
            data = self.dataset.load_new_data(file_name)
            
            self.pre_init_data = torch.tensor(data[None,data_start_frame-1]).to(self.device)
        
            data = self.dataset.denorm_data(data[data_start_frame:data_end_frame])

            #print(data[10:12,self.dataset.joint_dim_lst[0]:self.dataset.joint_dim_lst[1]])
            data_trajs = self.dataset.x_to_trajs(data)
            #data_jnts = self.dataset.x_to_jnts(data, mode='position')
            #self.dataset.plot_jnts(data_jnts[None,...])
            self.waypoints = torch.tensor(data_trajs).to(self.device).float()
            data = torch.tensor(data).to(self.device).float()
            
            content[:, start_frame:end_frame, :dim_lst[1]] = data[:,:dim_lst[1]]
            mask[:, start_frame:end_frame, :dim_lst[1]] = 1

            #print(self.waypoints.shape)

        elif 'full_rotation' in edit_dict:
            data_start_frame = edit_dict['full_rotation']['data_start_frame']
            data_end_frame = edit_dict['full_rotation']['data_end_frame']
            start_frame = edit_dict['full_rotation']['start_frame']
            end_frame = edit_dict['full_rotation']['end_frame']
            assert data_end_frame - data_start_frame == end_frame-start_frame
            dim_lst = list(range(self.dataset.angle_dim_lst[0], self.dataset.angle_dim_lst[1])) + [0,1,2]
            
            file_name = edit_dict['full_rotation']['val']
            data = self.dataset.load_new_data(file_name)
            self.pre_init_data = torch.tensor(data[None,data_start_frame-1]).to(self.device)
            data = torch.tensor(self.dataset.denorm_data(data[data_start_frame:data_end_frame])).to(self.device).float()
            
            content[:, start_frame:end_frame, dim_lst] = data[None,:,dim_lst]
            mask[:, start_frame:end_frame, dim_lst] = 1

        elif 'full_joint' in edit_dict: #not working well
            data_start_frame = edit_dict['full_joint']['data_start_frame']
            data_end_frame = edit_dict['full_joint']['data_end_frame']
            start_frame = edit_dict['full_joint']['start_frame']
            end_frame = edit_dict['full_joint']['end_frame']
            assert data_end_frame - data_start_frame == end_frame-start_frame

            elbow_left_dim = self.dataset.get_dim_by_key('position','LeftForeArm')
            hand_left_dim = self.dataset.get_dim_by_key('position','LeftHand')
            
            elbow_right_dim = self.dataset.get_dim_by_key('position','RightForeArm')
            hand_right_dim = self.dataset.get_dim_by_key('position','RightHand')
            head_dim = self.dataset.get_dim_by_key('position','Head')

            ###svr setting #
            rot_dim= self.dataset.get_dim_by_key('heading',None)
            dim_lst = hand_left_dim + hand_right_dim + elbow_left_dim + elbow_right_dim + head_dim + [0,1] + list(range(rot_dim[0],rot_dim[1]))
            #dim_lst = list(range(self.dataset.joint_dim_lst[0], self.dataset.joint_dim_lst[1])) + [0,1,2]
            file_name = edit_dict['full_joint']['val']
            data = self.dataset.load_new_data(file_name)
            self.pre_init_data = torch.tensor(data[None,data_start_frame-1]).to(self.device)
            data = torch.tensor(self.dataset.denorm_data(data[data_start_frame:data_end_frame])).to(self.device).float()
            
            content[:, start_frame:end_frame, dim_lst] = data[None,:,dim_lst]
            mask[:, start_frame:end_frame, dim_lst] = 1

        if 'trajectory' in edit_dict:
            dim_lst = self.dataset.get_dim_by_key('heading',None)

            self.p_control = True
            start_frame = edit_dict['trajectory']['start_frame']
            end_frame = edit_dict['trajectory']['end_frame']
            self.waypoints = torch.zeros((self.num_parallel, self.max_timestep, 2)).to(self.device)
            self.waypoint_heading = torch.zeros((self.num_parallel, self.max_timestep, 1)).to(self.device)
            if edit_dict['trajectory']['shape'] == 'line':

                speed = 75.0/self.max_timestep
                self.waypoints[..., 1] = torch.arange(self.max_timestep)[None,...].to(self.device) * speed
                self.waypoint_heading[...] = math.pi
                mask[:, start_frame: end_frame, [0,1]] = 1
                mask[:, start_frame: end_frame, dim_lst[0]:dim_lst[1]] = 1
                content[:, start_frame: end_frame, 0] = 0
                content[:, start_frame: end_frame, 1] = -speed 
                content[:, start_frame: end_frame, dim_lst[0]:dim_lst[1]] = self.dataset.get_heading_from_val(0) 
                #cur_facing = self.root_facing,
                #cur_pos = self.root_xz

            elif edit_dict['trajectory']['shape'] == 'circle':
                #steps = torch.arange(self.max_timestep)*2/self.max_timestep * math.pi
                max_timestep = 640
                R = edit_dict['trajectory'].get('radius',13)
                dir = edit_dict['trajectory'].get('direction', 'forward')

                if dir == 'forward':
                    content[:, start_frame: end_frame, 0] = 0
                    content[:, start_frame: end_frame, 1] = -2*math.pi*R/max_timestep
                elif dir == 'backward':
                    content[:, start_frame: end_frame, 0] = 0
                    content[:, start_frame: end_frame, 1] = 2*math.pi*R/max_timestep
                elif dir == 'side1':
                    content[:, start_frame: end_frame, 0] = 2*math.pi*R/max_timestep
                    content[:, start_frame: end_frame, 1] = 0
                elif dir == 'side2':
                    content[:, start_frame: end_frame, 0] = -2*math.pi*R/max_timestep
                    content[:, start_frame: end_frame, 1] = 0

                mask[:, start_frame: end_frame, [0,1]] = 1
                mask[:, start_frame: end_frame, dim_lst[0]:dim_lst[1]] =1 
                
                content[:, start_frame: end_frame, dim_lst[0]:dim_lst[1]] = self.dataset.get_heading_from_val(2*math.pi/max_timestep)#self.max_timestep)

            #print(content.shape)
            trajs = self.dataset.x_to_trajs(content[0].cpu().detach().numpy())
            self.waypoints[..., 0] = torch.from_numpy(trajs[...,0])
            self.waypoints[..., 1] = torch.from_numpy(trajs[...,1])

        if 'heading' in edit_dict:   
            dim_lst = self.dataset.get_dim_by_key('heading',None)
            
            edit_val = edit_dict['heading']['val']
            start_frame = edit_dict['heading']['start_frame']
            end_frame = edit_dict['heading']['end_frame']
            mask[:, start_frame: end_frame, dim_lst[0]: dim_lst[1]] = 1
            
            if isinstance(edit_val, str):
                val = np.load(edit_val)
                val = torch.tensor(val).to(self.device)
                assert val.shape[0] == end_frame - start_frame

                content[:, start_frame: end_frame, dim_lst[0]: dim_lst[1]] = self.dataset.get_heading_from_val(val)
            else:
                content[:, start_frame: end_frame, dim_lst[0]: dim_lst[1]] = self.dataset.get_heading_from_val(edit_val) #torch.tensor(edit_val).to(self.device)
        

        if 'root_dxdy' in edit_dict:   
            dim_lst = self.dataset.get_dim_by_key('root_dxdy',None)
            cur_dict = edit_dict['root_dxdy']
            for num in cur_dict:         
                edit_dim = dim_lst[num]

                edit_val = cur_dict[num]['val']
                start_frame = cur_dict[num]['start_frame']
                end_frame = cur_dict[num]['end_frame']
                mask[:, start_frame: end_frame, edit_dim] = 1
                if isinstance(edit_val, str):
                    val = np.load(edit_val)
                    val = torch.tensor(val).to(self.device)
                    content[:, start_frame: end_frame, edit_dim] = val
                else:
                    content[:, start_frame: end_frame, edit_dim] = edit_val
                

        for elem in ['position', 'velocity', 'angle']:
            if elem in edit_dict:
                for key in edit_dict[elem]:
                    dim_lst = self.dataset.get_dim_by_key(elem, key)
                    start_dim = dim_lst[0]
                    end_dim = dim_lst[1]
                    cur_dict = edit_dict[elem][key]
                    for num in cur_dict: 
                        
                        start_frame = edit_dict[elem][key][num]['start_frame']
                        end_frame = edit_dict[elem][key][num]['end_frame']
                        edit_dim = start_dim+num
                        edit_val = edit_dict[elem][key][num]['val']
                        mask[:, start_frame: end_frame, edit_dim] = 1
                        if isinstance(edit_val, str):
                            val = np.load(edit_val)
                            val = torch.tensor(val).to(self.device)
                            content[:, start_frame: end_frame, edit_dim] = val
                        else:
                            content[:, start_frame: end_frame, edit_dim] = edit_val
                   
                        #edit_val = torch.tensor(edit_val).to(self.device)
                        #content[:, start_frame: end_frame, start_dim: end_dim] = edit_val[None,...]
        
                    
        content = self.dataset.norm_data(content, device=content.device)
        #content = content.view(self.num_parallel, self.max_timestep, self.frame_dim)
        
        return mask, content

    def update_textemb(self, text):
        if text is None or len(text) == 0:
            print('text',self.dataset.use_cond)
            if self.dataset.use_cond:
                self.text_emb = torch.zeros((self.num_parallel, self.dataset.cond_embedding_dim)).to(self.device)
            else:
                self.text_emb = None
        else:
            if len(text) == self.num_parallel:
                self.text_emb = self.dataset.get_clip_class_embedding(text,outformat='pt').to(self.device)
                
            elif len(text) > self.num_parallel:
                self.text_emb = self.dataset.get_clip_class_embedding(text[:self.num_parallel],outformat='pt').to(self.device)
            else:
                text = text + [text[-1] for _ in range(self.num_parallel-len(text))]
                self.text_emb = self.dataset.get_clip_class_embedding(text, outformat='pt').to(self.device)

        self.updated_text = True
        self.cur_extra_info = {'cond':self.text_emb, **self.cur_extra_info}

    
    def check_update_text(self):
        lock = FileLock(user_input_lockfile + ".lock")
        with lock:
            file = open(user_input_lockfile, "r")
            lines = file.readlines()[0]            
            file.close()
        if lines == ';'.join(self.texts):
            self.updated_text = True
        else:
            print(lines)
            self.texts = lines.strip().split(';')
            self.updated_text = False


    def reset_initial_frames(self, frame_index=None):
        # Make sure condition_range doesn't blow up
        if self.pre_init_data is None:
            num_frame_used = len(self.valid_idx)
            num_init = self.num_parallel if frame_index is None else len(frame_index)
            #start_index = 37300
            start_index = torch.randint(0,num_frame_used-1,(num_init,1)) 
            start_index = self.valid_idx[start_index]
            
            data = torch.tensor(self.dataset.motion_flattened[start_index]).to(self.device)
           
        else:
            data = self.pre_init_data
        
        if frame_index is None:
            self.init_frame = data.clone()
            self.history[:, :self.num_condition_frames] = data.clone()
        else:
            self.init_frame[frame_index] = data.clone()
            self.history[frame_index, :self.num_condition_frames] = data.clone()


    def get_next_frame(self, action=None):
        if self.interative_text:
            self.check_update_text()
            if not self.updated_text:
                print('infer text',self.texts)
                self.update_textemb(self.texts)

        condition = self.get_cond_frame()
        b = condition.shape[0]
        
        cur_extra_info = self.cur_extra_info
        if self.stopsteps is not None:
            stopstep = self.stopsteps[...,self.record_timestep]
            cur_extra_info['interact_stop_step'] = stopstep
        '''
        import copy
        if self.cur_target in self.st_frame_dict:
            start_frame = self.st_frame_dict[self.cur_target] 
            cur_extra_info = copy.deepcopy(self.cur_extra_info)
            if self.record_timestep > start_frame + 70:
                self.cur_target += 1
            
        '''
        with torch.no_grad():
            '''
            if start_frame < self.record_timestep <= start_frame + 65:# or self.record_timestep>self.end_frame - 15 :
                cur_extra_info['interact_stop_step'] = 35#20 + int(20 * (1-((self.record_timestep-start_frame)/70.0))) #35 #int(30 * (1-((self.record_timestep-self.start_frame)/30.0)))
            #print(cur_extra_info['interact_stop_step'] )
            else:
                cur_extra_info['interact_stop_step'] = 18
            '''
            output = self.model.eval_step_interactive(condition,  self.mask[:,self.record_timestep], self.content[:,self.record_timestep], cur_extra_info)
            
        output = output.view(-1,self.frame_dim)
        #output = self.dataset.denorm_data(output.cpu()).to(self.device)
        
        if self.is_rendered:
            self.record_motion_seq[:,self.record_timestep,:]=output.cpu().detach().numpy()
            self.record_timestep += 1
            if self.record_timestep % 30 == 0 and self.record_timestep != 0:
                self.save_motion()
                if self.waypoints is not None:
                    np.save(osp.join(self.int_output_dir,'waypoint.npy'),self.waypoints.squeeze().cpu().numpy())
        
        #self.update_new_frame_with_state(output)
        
        return output
    
    def update_new_frame_with_state(self, frame_deformed):
        if self.record_timestep >= self.max_timestep-1:
            return 
        
        if self.p_control and self.waypoints is not None: 
            pred_dxdydr = frame_deformed[:, :3]
            thetaf = self.waypoint_heading[:, self.record_timestep+1]
            
            rf = frame_deformed[:, 2]

            pred_r = ((self.root_facing + rf)%(math.pi*2)).squeeze(-1)
            #print(rf.shape, pred_r.shape)
            radj = 0.5 * geo_util.angle_difference(thetaf, pred_r)[...,0]
            
            self.content = self.dataset.denorm_data(self.content, device = self.device)#.float()
            self.content[:, self.record_timestep+1, 2] -= radj
            #self.content[:, self.record_timestep+1, :2] -= vadj
            #print(pred_r, radj, self.content[:, self.record_timestep+1, 2])
            self.content = self.dataset.norm_data(self.content, device = self.device).float()
            self.mask[:, self.record_timestep+1, 2] = 1.0 



    def get_observation_components(self):
        self.base_action.normal_(0, 1)
        condition = self.get_cond_frame()
        return condition, self.base_action


    def reset(self, indices=None):
        self.timestep = 0
        self.substep = 0
        self.root_facing.fill_(0)
        self.root_xz.fill_(0)
        self.done.fill_(False)

        # Need to clear this if we want to use calc_foot_slide()
        self.reset_initial_frames()
        #obs_components = self.get_observation_components()

        #return torch.cat(obs_components, dim=-1)
    

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        is_external_step = self.substep == 0

        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip

        self.integrate_root_translation(next_frame)

        self.reward.fill_(1)  
      
        #foot_slide = self.calc_foot_slide()
        #self.reward.add_(foot_slide.sum(dim=-1, keepdim=True) * -10.0)

        obs_components = self.get_observation_components()
        self.done.fill_(self.timestep >= self.max_timestep)

        self.render()
        return (
            None,#torch.cat(obs_components, dim=1),
            self.reward,
            self.done,
            {"reset": self.timestep >= self.max_timestep},
        )
    
    def render(self, mode="human"):
        frame = self.dataset.denorm_data(self.history[:, 0], device=self.device).cpu().numpy()
        if self.is_rendered:
            self.viewer.render(
                torch.tensor(self.dataset.x_to_jnts(frame, mode='angle'),device=self.device),  # 0 is the newest
                self.root_facing,
                self.root_xz,
                0.0,  # No time in this env
                self.action,
            )
    def dump_additional_render_data(self):
        from common.misc_utils import POSE_CSV_HEADER

        current_frame = self.history[:, 0]
        pose_data = current_frame[:, 0:8+self.num_joint*3]

        data_dict = {
            "pose{}.csv".format(index): {"header": POSE_CSV_HEADER}
            for index in range(pose_data.shape[0])
        }
        for index, pose in enumerate(pose_data):
            key = "pose{}.csv".format(index)
            data_dict[key]["data"] = pose.clone()

        self.gui_process.join()
        return data_dict
