
import policy.envs.base_env as base_env
from render.realtime.mocap_renderer import PBLMocapViewer
import torch
import numpy as np
import tkinter as tk
import gymnasium as gym

from multiprocessing import Process
from filelock import FileLock

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


class SampleTaskEnv(base_env.EnvBase):
    NAME = "SampleTask"
    def __init__(self, config, model, dataset, device):      
        super().__init__(config, model, dataset, device)

        self.device = device
        self.config = config
        self.model = model
        self.dataset = dataset
        
        self.links = self.dataset.links
        self.valid_idx = self.dataset.valid_idx

        self.interative_text = False
        self.cur_extra_info = None
        self.updated_text = False

        if 'text' in config:
            print('-------------tyext')
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
        self.num_candidate = config['num_candidate']
        self.max_timestep = 10000
        
        self.arena_length = (-15.0, 15.0)
        self.arena_width = (-15.0, 15.0)
        #self.max_timestep = 1200/ 
        # 2D delta to task in root space

        self.index_of_target = 0
        target_dim = 2
        self.target = torch.zeros((self.num_parallel, target_dim)).to(self.device)

        self.action_dim = self.frame_dim
        self.timestep = 0
        self.substep = 0
        self.base_action = torch.zeros((self.num_parallel, 1, self.action_dim)).to(self.device)

        self.num_candidate = self.config['num_candidate']
        self.task_frame_buffer = [[] for _ in range(self.num_parallel)]
        self.task_location_buffer = torch.zeros((self.num_parallel, 2)) 

        high = np.inf * np.ones([self.action_dim])
        self.action_space = gym.spaces.Box(-high, high, dtype=np.float32)

        self.observation_dim = (
            self.frame_dim * self.num_condition_frames + self.action_dim
        )

        high = np.inf * np.ones([self.observation_dim])
        self.observation_space = gym.spaces.Box(-high, high, dtype=np.float32)

    
    def update_textemb(self, text):
        if text is None or len(text) == 0:
            print('tetxtedtetxet',self.dataset.use_cond)
            if self.dataset.use_cond:
                self.text_emb = torch.zeros((self.num_parallel, self.dataset.cond_embedding_dim)).to(self.device)
            else:
                self.text_emb = None
        else:
            if len(text) == self.num_parallel:
                self.text_emb = self.dataset.get_clip_class_embedding(text,outformat='pt')
                
            elif len(text) > self.num_parallel:
                self.text_emb = self.dataset.get_clip_class_embedding(text[:self.num_parallel],outformat='pt')
            else:
                text = text + [text[-1] for _ in range(self.num_parallel-len(text))]
                self.text_emb = self.dataset.get_clip_class_embedding(text, outformat='pt')

        self.updated_text = True
        self.cur_extra_info = {'cond':self.text_emb}
    

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


    def compute_distance(self, pos, target):        
        #root_pos = self.viewer.root_xyzs
        pos = pos.reshape(-1,self.num_candidate, pos.shape[-1])
        target = target[:,None,:].expand(-1,self.num_candidate,-1)
        dist = torch.norm(target - pos,dim=-1)
        return dist


    def step_candidate(self, frames):
        root_facing = self.root_facing[:,None,:].expand(-1,self.num_candidate,-1).reshape(-1, self.root_facing.shape[-1])
        root_xz = self.root_xz[:,None,:].expand(-1,self.num_candidate,-1).reshape(-1, self.root_xz.shape[-1])
        #print(root_facing.shape, frames.shape)
        cur_facing =root_facing + frames[:, [2]]
        cur_facing.remainder_(2 * np.pi)
        cur_mat = self.get_rotation_matrix(cur_facing)
        displacement = (cur_mat * frames[:, :2].unsqueeze(1)).sum(dim=2)
        root_xz = displacement + root_xz
        return root_xz


    def greedy_search(self, condition_frames):
        #condition_frames charxF
        #torch.manual_seed(7777) #67777
        condition_frames = condition_frames[:,None,:].expand(-1,self.num_candidate,-1)
        condition_frames = condition_frames.reshape(-1,self.frame_dim)
        print(condition_frames.shape)
        with torch.no_grad():
            frames = self.model.eval_step(condition_frames, self.cur_extra_info)
        frames = self.dataset.denorm_data(frames.cpu()).to(self.device)
        #frames = frames.view(self.num_parallel, self.num_candidate, -1)
        cur_pos = self.step_candidate(frames)
        dist = self.compute_distance(cur_pos, self.target).reshape(self.num_parallel, self.num_candidate)
      
        best_frames_index = torch.argmin(dist,axis=-1)
        frames = frames.reshape(-1,self.num_candidate,self.frame_dim)
        best_frames = frames[torch.arange(frames.shape[0]), best_frames_index]
        
        return best_frames


    def get_next_frame(self, action=None):
        
        if self.interative_text:
            self.check_update_text()
            if not self.updated_text:
                print('infer text',self.texts)
                self.update_textemb(self.texts)
        
        condition = self.get_cond_frame()
        b = condition.shape[0]
        #print(condition.shape)
        output = self.greedy_search(condition)
        #print(output.shape)
        #output = output.view(1,-1,self.frame_dim)
        if self.is_rendered:
            self.record_motion_seq[:,self.record_timestep,:]=output.cpu().detach().numpy()
            if self.record_timestep % 10 == 0:
                self.save_motion()
            self.record_timestep += 1
        return output
        

    def get_observation_components(self):
        
        condition = self.get_cond_frame()
        return condition#, self.base_action

    
    def reset_target(self, indices=None, location=None):
        if location is None:
            #print(self.target.device)
            if indices is None:
                self.target[:, 0].uniform_(*self.arena_length)
                self.target[:, 1].uniform_(*self.arena_width)
            else:
                # if indices is a pytorch tensor, this returns a new storage
                new_lengths = self.target[indices, 0].uniform_(*self.arena_length)
                self.target[:, 0].index_copy_(dim=0, index=indices, source=new_lengths)
                new_widths = self.target[indices, 1].uniform_(*self.arena_width)
                self.target[:, 1].index_copy_(dim=0, index=indices, source=new_widths)
            
            
            targets_lst =torch.tensor([[-5.0,5.0]]).to(self.device)
            #          [ -20.0, -14.0],
            #          [ -14.0, -20.0],
            #          #[ -40.0, -25.0],
            #         [-4.0,-15.0],
            #         [24.0, 15.0]
                      #[ -19.2380, -45.6012],
                      #[39.2380, 70],
                      #[50,47],
                      #[33,60],
            #          ])

            self.target = targets_lst[None,self.index_of_target]
            self.index_of_target += 1
           
            
        else:
            # Reaches this branch only with mouse click in render mode
            self.target[:, 0] = location[0]
            self.target[:, 1] = location[1]
            
        print(self.target)
        
        if self.is_rendered:
            self.viewer.update_target_markers(self.target)
        
        self.calc_potential()

    def reset(self, indices=None):
        if indices is None:
            self.root_facing.fill_(0)
            self.root_xz.fill_(0)
            self.reward.fill_(0)
            self.timestep = 0
            self.substep = 0
            self.done.fill_(False)
            # value bigger than contact_threshold
            #self.foot_pos_history.fill_(1)

            self.reset_target()
            self.reset_initial_frames()
        else:
            self.root_facing.index_fill_(dim=0, index=indices, value=0)
            self.root_xz.index_fill_(dim=0, index=indices, value=0)
            self.reward.index_fill_(dim=0, index=indices, value=0)
            self.done.index_fill_(dim=0, index=indices, value=False)
            self.reset_target(indices)

            # value bigger than contact_threshold
            #self.foot_pos_history.index_fill_(dim=0, index=indices, value=1)

        obs_components = self.get_observation_components()
        return obs_components
    
    def reset_index(self, indices=None):
        if indices is None:
            self.root_facing.fill_(0)
            self.root_xz.fill_(0)
            self.reward.fill_(0)
            self.timestep = 0
            self.substep = 0
            self.done.fill_(False)
            # value bigger than contact_threshold
            #self.foot_pos_history.fill_(1)

            self.reset_target()
            self.reset_initial_frames()
        else:
            self.root_facing.index_fill_(dim=0, index=indices, value=0)
            self.root_xz.index_fill_(dim=0, index=indices, value=0)
            self.reward.index_fill_(dim=0, index=indices, value=0)
            self.done.index_fill_(dim=0, index=indices, value=False)
            self.reset_target(indices)

            # value bigger than contact_threshold
            #self.foot_pos_history.index_fill_(dim=0, index=indices, value=1)

        obs_components = self.get_observation_components()
        return obs_components
    

    def calc_progress_reward(self):
        old_linear_potential = self.linear_potential
        old_angular_potential = self.angular_potential

        self.calc_potential()
        linear_progress = self.linear_potential - old_linear_potential
        angular_progress = self.angular_potential - old_angular_potential
        progress = linear_progress
        
        return progress

    def calc_potential(self):
        target_xy_delta, target_z_delta, target_angle = self.get_target_delta_and_angle()
        #target_delta = torch.cat([target_xy_delta, target_z_delta],dim=-1)
        #print(target_xy_delta, target_z_delta, target_delta, target_xy_delta.norm(dim=1))
        self.linear_potential = -target_xy_delta.norm(dim=1).unsqueeze(1)  #np.sqrt(target_xy_delta.norm(dim=1)**2+target_z_delta**2)
        self.delta_z = -target_z_delta
        self.angular_potential = target_angle.cos()

    def get_target_delta_and_angle(self):
        target_xy_delta = self.target[:,:2] - self.root_xz
        target_z_delta = self.target[:,2:] - self.root_y
        target_angle = (
            torch.atan2(target_xy_delta[:, 1], target_xy_delta[:, 0]).unsqueeze(1)
            + self.root_facing
        )
        #target_delta = torch.cat([target_xy_delta, target_z_delta],dim=-1)
        return target_xy_delta, target_z_delta, target_angle

    def calc_env_state(self, next_frame):
        self.next_frame = next_frame
        is_external_step = self.substep == 0

        if self.substep == self.frame_skip - 1:
            self.timestep += 1
        self.substep = (self.substep + 1) % self.frame_skip

        self.integrate_root_translation(next_frame)

        self.calc_progress_reward()
        target_dist = -self.linear_potential
        target_is_close = target_dist < 2
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

    def dump_additional_render_data(self):
        from common.misc_utils import POSE_CSV_HEADER

        current_frame = self.history[:, 0]
        pose_data = current_frame[:, 0:3+self.num_joint*3]

        data_dict = {
            "pose{}.csv".format(index): {"header": POSE_CSV_HEADER}
            for index in range(pose_data.shape[0])
        }
        for index, pose in enumerate(pose_data):
            key = "pose{}.csv".format(index)
            data_dict[key]["data"] = pose.clone()

        self.gui_process.join()
        return data_dict
