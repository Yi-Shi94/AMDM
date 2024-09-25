import numpy as np
import copy
import torch
from tqdm import tqdm
import model.trainer_base as trainer_base

class AMDMTrainer(trainer_base.BaseTrainer):
    NAME = 'AMDM_TEXT'
    def __init__(self, config, dataset, device):
        super(AMDMTrainer, self).__init__(config, dataset, device)
        optimizer_config = config['optimizer']
        self.full_T = optimizer_config.get('full_T', False)
        self.consistency_on = optimizer_config.get('consistency_on', False)
        self.consist_loss_weight = optimizer_config.get('consist_loss_weight',1)
        self.loss_type = config["diffusion"]["loss_type"] 
        self.recon_on = optimizer_config.get('recon_on', False)
        self.recon_loss_weight = optimizer_config.get('recon_loss_weight', 1)
        self.diffusion_loss_weight = optimizer_config.get('diffusion_loss_weight', 1)
        self.detach_step = optimizer_config.get('detach_step',3)


    def compute_rpr_consist_loss(self, last_frame, cur_frame):
        cur_frame_denormed = self.dataset.denorm_data(cur_frame, device=cur_frame.device)
        last_frame_denormed = self.dataset.denorm_data(last_frame, device=last_frame.device)  
        
        jnts = self.dataset.jnts_frame_pt(cur_frame_denormed)
        if self.loss_type == 'l1':
            loss_fn = torch.nn.functional.l1_loss
        else:
            loss_fn = torch.nn.functional.mse_loss
        
        if 'angle' in self.dataset.data_component:
            jnts_fk = self.dataset.angle_frame_pt(cur_frame_denormed)
            consist_loss_fk_jnts = loss_fn(jnts_fk, jnts.squeeze())
        else:
            consist_loss_fk_jnts = 0

        if 'velocity' in self.dataset.data_component: 
            jnts_vel = self.dataset.vel_frame_pt(last_frame_denormed, cur_frame_denormed)
            consist_loss_vel_jnts = loss_fn(jnts_vel, jnts.squeeze())
        else:
            consist_loss_vel_jnts = 0
        #consist_loss_fk_vel = loss_fn(jnts_vel, jnts_fk)
        return consist_loss_fk_jnts + consist_loss_vel_jnts
    

    def compute_teacher_loss(self, model, sampled_frames, extra_info):
        last_frame = sampled_frames[:,0,:]
        ground_truth = sampled_frames[:,1,:]
        
        self.optimizer.zero_grad()
        extra_info["text_embeddings"] = extra_info["text_embeddings"][:,0,:]
        diff_loss, pred_frame = model.compute_loss(last_frame,  ground_truth, None, extra_info)
        loss = self.diffusion_loss_weight * diff_loss 
    
        loss.backward()
        self.optimizer.step()
        model.update()

        return {"diff_loss":diff_loss.item()}
    

    def compute_student_loss(self, model, sampled_frames, sch_samp_prob, extra_info):
        loss_diff_sum, loss_consist_sum = 0, 0
        batch_size = sampled_frames.shape[0]
        shrinked_batch_size = batch_size//model.T
        text_embeddings = extra_info["text_embeddings"]

        for st_index in range(self.num_rollout -1):
            self.optimizer.zero_grad()
            next_index = st_index + 1
            ground_truth = sampled_frames[:,next_index,:]
            #text_embeddings = text_embeddings[:,next_index,:]

            if self.full_T:
                shrinked_batch_size = batch_size
                last_text_embeddings = text_embeddings[:,st_index,:]
                last_text_embeddings_expand = last_text_embeddings[:,None,:].expand(-1, model.T, -1).reshape(shrinked_batch_size*model.T, -1)
                
                if st_index == 0:
                    last_frame = sampled_frames[:,0,:]
                    last_frame_expanded = last_frame[:,None,:].expand(-1, model.T, -1).reshape(shrinked_batch_size*model.T, -1)
                    
                else:
                    last_frame = pred_frame.detach().reshape(shrinked_batch_size, model.T, -1)[:,0,:]
                    teacher_forcing_mask = torch.bernoulli(1.0-torch.ones(shrinked_batch_size, device=pred_frame.device) *sch_samp_prob).bool()
                    last_frame[teacher_forcing_mask] = sampled_frames[teacher_forcing_mask, st_index, :]
                    last_frame_expanded = last_frame[:,None,:].expand(-1, model.T, -1).reshape(shrinked_batch_size*model.T, -1)

                ground_truth_expanded = ground_truth[:,None,:].expand(-1, model.T, -1).reshape(shrinked_batch_size*model.T, -1)

                ts = torch.arange(0, model.T, device=self.device)
                ts = ts[None,...].expand(shrinked_batch_size,-1).reshape(-1)
                
                extra_info = {"text_embeddings":last_text_embeddings_expand} 
                diff_loss, pred_frame = model.compute_loss(last_frame_expanded, ground_truth_expanded, ts, extra_info)
                loss = self.diffusion_loss_weight * diff_loss

                
            else:
                last_text_embeddings = text_embeddings[:,st_index,:]

                if st_index == 0:
                    last_frame = sampled_frames[:,0,:]
                else:
                    last_frame = pred_frame.detach()
                    teacher_forcing_mask = torch.bernoulli(1.0-torch.ones(batch_size, device=pred_frame.device) * sch_samp_prob).bool()
                    last_frame[teacher_forcing_mask] = sampled_frames[teacher_forcing_mask,st_index,:]
                    
                extra_info = {"text_embeddings":last_text_embeddings} 
                diff_loss_teacher, _ = model.compute_loss(sampled_frames[:,st_index,:], ground_truth, None, extra_info)
                diff_loss_student, pred_frame = model.compute_loss(last_frame, ground_truth, None, extra_info)
                diff_loss =  diff_loss_student  +  diff_loss_teacher #/ self.num_rollout
                loss = self.diffusion_loss_weight * diff_loss
             

            loss.backward()
            self.optimizer.step()
            model.update()

            loss_diff_sum += diff_loss.item()
           
        
        return {"diff_loss": loss_diff_sum}
    

    def train_loop(self, ep, model):
        ep_loss_dict = {}

        num_samples = 0
        self._update_lr_schedule(self.optimizer, ep - 1)
        
        model.train()
        pbar = tqdm(self.train_dataloader, colour='green')
        cur_samples = 1
        for frames, text_embeddings in pbar:
           
            extra_info = {'text_embeddings': text_embeddings.to(self.device).float()}
            frames = frames.to(self.device).float()
            
            self.optimizer.zero_grad()

            if self.sample_schedule[ep]>0:
                loss_dict = self.compute_student_loss(model, frames, self.sample_schedule[ep], extra_info=extra_info)   
            else:
                loss_dict= self.compute_teacher_loss(model, frames, extra_info=extra_info)
            
            
            num_samples += cur_samples
            
            loss = 0
            for key in loss_dict:
                loss += loss_dict[key]
                if key not in ep_loss_dict:
                    ep_loss_dict[key] = loss_dict[key]
                else:
                    ep_loss_dict[key] += loss_dict[key]
                
            
            out_str = ' '.join(['{}:{:.4f}'.format(key,val) for key, val in loss_dict.items()])            
            pbar.set_description('ep:{}, {}'.format(ep, out_str))

        for key in loss_dict:
            ep_loss_dict[key] /= num_samples

        train_info = {
                    "epoch": ep,
                    "sch_smp_rate": self.sample_schedule[ep],
                    **ep_loss_dict
                }
        
        return train_info

    def evaluate(self, ep, model, result_ouput_dir):
        model.eval()
        NaN_clip_num = 0
        texts = ['a man walk straight forward','the character jumps up and down','a man standing on his left foot', 'a man is crawling on the ground', 'the character is performing cartwheel']
        text_embs = self.dataset.encode_text(texts)

        for idx, (st_idx, ref_clip) in enumerate(zip(self.dataset.test_valid_idx, self.dataset.test_ref_clips)):
            
            text_idx = idx % len(texts)
            text = texts[text_idx]
            text_emb = torch.as_tensor(text_embs[text_idx][None,...]).float().to(self.device)
            extra_dict = {"text_embeddings":text_emb}

            test_out_lst = []
            test_local_out_lst = []

            print('Evaluating: starting index:{}, text:{}'.format(st_idx,text))

            start_x = torch.from_numpy(ref_clip[0]).float().to(self.device)
            
            if ep == 0:
                model_lst = self.dataset.data_component           
                cur_jnts = []
                for mode in model_lst:
                    jnts_mode = self.dataset.x_to_jnts(self.dataset.denorm_data(ref_clip), mode=mode)
                    cur_jnts.append(jnts_mode)
                cur_jnts = np.array(cur_jnts)

                self.plot_jnts_fn(cur_jnts.squeeze(), result_ouput_dir+'/gt_{}'.format(st_idx))
                ref_clip = cur_jnts[[0],...]
            else:
                ref_clip = self.dataset.x_to_jnts(self.dataset.denorm_data(ref_clip), mode=self.dataset.data_component[0])[None,...]
            
            test_out_lst.append(ref_clip.squeeze())
            test_data = model.eval_seq(start_x, extra_dict, self.test_num_steps, self.test_num_trials)
            test_data_long = model.eval_seq(start_x, extra_dict, 1000, 3)

            num_all = torch.numel(test_data)
            num_nans = torch.sum(torch.isnan(test_data))

            num_all_long = torch.numel(test_data_long)
            num_nans_long = torch.sum(torch.isnan(test_data_long))
        
            print('percent of nan frames : {}'.format(num_nans*1.0/num_all))
            print('percent of nan frames for long horizon gen : {}'.format(num_nans_long*1.0/num_all_long))
            should_plot = True
            if num_nans > 0:
                NaN_clip_num += 1
                should_plot = False
                #print('skip calc stats {} to save time'.format(st_idx))
                #if False:#NaN_clip_num >= len(self.dataset.test_valid_idx)-1:
                #continue # skip calc stats to save time
                        
            test_data = test_data.detach().cpu().numpy()

            for i in range(test_data.shape[0]):
                cur_denormed_test_data = self.dataset.denorm_data(copy.deepcopy(test_data[i]))
                cur_jnts = []
               
                for mode in self.dataset.data_component:
                    jnts_mode = self.dataset.x_to_jnts(cur_denormed_test_data, mode = mode)
                    cur_jnts.append(jnts_mode)

                    if mode == self.dataset.data_component[0]:
                        test_out_lst.append(jnts_mode)
                        jnts_mode_local = jnts_mode - jnts_mode[:,[0],:]  
                        test_local_out_lst.append(jnts_mode_local)
                cur_jnts = np.array(cur_jnts)
                if should_plot:
                    self.plot_jnts_fn(cur_jnts.squeeze(), result_ouput_dir+'/{}_{}_{}'.format(st_idx,text,i))
            test_out_lst = np.array(test_out_lst)
            self.plot_traj_fn(test_out_lst, result_ouput_dir+'/{}'.format(st_idx))
            
            test_data_long = test_data_long.detach().cpu().numpy()
            test_out_long_lst = []
            for i in range(test_data_long.shape[0]):
                cur_denormed_test_data = self.dataset.denorm_data(copy.deepcopy(test_data_long[i]))
                cur_jnts = []
               
                for mode in self.dataset.data_component:
                    jnts_mode = self.dataset.x_to_jnts(cur_denormed_test_data, mode = mode)
                    cur_jnts.append(jnts_mode)

                    if mode == self.dataset.data_component[0]:
                        test_out_long_lst.append(jnts_mode)
                        jnts_mode_local = jnts_mode - jnts_mode[:,[0],:]  
                cur_jnts = np.array(cur_jnts)
              
            test_out_long_lst = np.array(test_out_long_lst)
            self.plot_traj_fn(test_out_long_lst, result_ouput_dir+'/{}_{}_long'.format(st_idx, text))

        return NaN_clip_num