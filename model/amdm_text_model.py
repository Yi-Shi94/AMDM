import copy
import numpy as np
import math
import torch
import torch.nn as nn
import torch.nn.functional as f
from functools import partial
from copy import deepcopy
import random

import model.model_base as model_base
import model.modules.EMA as EMA 
import model.modules.Embedding as Embedding
import model.modules.Activation as Activation

import dataset.util.geo as geo_util


class AMDM(model_base.BaseModel):
    NAME = 'AMDM_TEXT'
    def __init__(self, config, dataset, device):
        super().__init__(config, dataset, device)
       
        self.estimate_mode = config["diffusion"]["estimate_mode"]   
        self.loss_type = config["diffusion"]["loss_type"] 
        
        self.T = config["diffusion"]["T"] 
        self.sample_mode = config["diffusion"]["sample_mode"]  
        self.eval_T = config["diffusion"]["eval_T"] if self.sample_mode == 'ddim' else self.T

        self.frame_dim = dataset.frame_dim
        config['frame_dim'] = self.frame_dim
        config["model_hyperparam"]['input_text_emb_dim'] = dataset.text_emb_dim
        
        self._build_model(config)

        self.use_ema = config["optimizer"].get("EMA", False)
        if self.use_ema:
            print("Using EMA")
            self.ema_step = 0
            self.ema_decay = config['optimizer']['EMA']['ema_decay']
            self.ema_start = config['optimizer']['EMA']['ema_start']
            self.ema_update_rate = config['optimizer']['EMA']['ema_update_rate']
            self.ema_diffusion = deepcopy(self.diffusion)
            self.ema = EMA.EMA(self.ema_decay)
        return

    def forward(self, input_lastx, input_noises, input_ts):
        x = input_noises[:, self.T]
        for t in range(self.T - 1, -1, -1):
            ts = input_ts[:, t]
            te = self.diffusion.time_mlp(ts)
            pred = self.diffusion.model(input_lastx, x, te)
            x = self.diffusion.remove_noise(x, pred, ts)
            if t > 0:
                x = self.diffusion.add_noise_w(x, ts, input_noises[:,t])
        return x

    def _build_model(self, config):
        self.diffusion = GaussianDiffusion(config)
        self.diffusion.to(self.device)
        return

    def eval_step(self, cur_x, extra_dict, align_rpr=False, record_process=False): 
        diffusion = self.ema_diffusion if self.use_ema else self.diffusion  
        with torch.no_grad():
            if self.sample_mode == 'ddpm':
                next_x =  diffusion.sample_ddpm(cur_x, extra_dict)
           
            else:
                assert(False), "Unsupported estimate mode:{}".format(self.estimate_mode)

        if align_rpr:
            next_x = self.align_frame_with_angle(cur_x, next_x).type(cur_x.dtype)

        return next_x

    def rl_step(self, start_x, action_dict, extra_dict):
        diffusion = self.ema_diffusion if self.use_ema else self.diffusion 
        return diffusion.sample_rl_ddpm(start_x, action_dict, extra_dict)

    
    def eval_seq(self, start_x, extra_dict, num_steps, num_trials, align_rpr=False, record_process=False):
        diffusion = self.ema_diffusion if self.use_ema else self.diffusion  

        if start_x is None:
            start_x = diffusion.sample_ddpm_firstframe(num_trials, extra_dict, self.device)
        
        if len(start_x.shape)<=1:
            start_x = start_x[None,:]
        
        if start_x.shape[0] == 1:
            start_x = start_x.expand(num_trials, -1)
            #etxt_embeddings = extra_dict['text_embeddings'].expand(num_trials, -1)
            cur_extra_dict = {}
            for item in extra_dict:
                cur_extra_dict[item] = extra_dict[item].expand(num_trials, -1)
        else:
            print('overwrite num of trial with actual batch size of start_x')
            num_trials = start_x.shape[0]
            cur_extra_dict = {}
            for item in extra_dict:
                cur_extra_dict[item] = extra_dict[item]

        if record_process:
            output_xs = torch.zeros((num_trials, num_steps, self.T, self.frame_dim)).to(self.device)
        else:
            output_xs = torch.zeros((num_trials, num_steps, self.frame_dim)).to(self.device)

        for j in range(num_steps):
            with torch.no_grad():
                start_x = self.eval_step(start_x, cur_extra_dict, align_rpr, record_process).detach()
            output_xs[:,j,...] = start_x 
            
            if record_process:
                start_x= start_x[...,-1,:]

        return output_xs

    def eval_step_interactive(self, cur_x, edited_mask, edit_data, extra_dict): 
        diffusion = self.ema_diffusion if self.use_ema else self.diffusion

        if self.sample_mode == 'ddpm':
            return diffusion.sample_ddpm_interactive(cur_x, edited_mask, edit_data, extra_dict)
        #elif self.sample_mode == 'ddim':
        #    return self.model.sample_ddim_interactive(cur_x, self.eval_T, edited_data, edited_mask, extra_dict)
        else:
            assert(False), "Unsupported agent: {}".format(self.estimate_mode)                

    def eval_seq_interactive(self, start_x, extra_dict, edit_data, edited_mask, num_steps, num_trials):
        output_xs = torch.zeros((num_trials, num_steps, self.frame_dim)).to(self.device)
        start_x = start_x[None,:].expand(num_trials, -1)
        for j in range(num_steps):
            with torch.no_grad():
                start_x = self.eval_step_interactive(start_x, edit_data[j], edited_mask[j], extra_dict).detach()
            output_xs[:,j,:] = start_x 
        return output_xs


    def compute_loss(self, last_x, next_x, ts, extra_dict):
        estimated, noise, xt, ts = self.diffusion(last_x, next_x, ts, extra_dict)   
        if self.estimate_mode == 'x0':
            target = next_x
            pred_x0 = estimated

        elif self.estimate_mode == 'epsilon':
            target = noise
            pred_x0 = self.diffusion.get_x0_from_xt(xt, ts, estimated)
        
        else:
            assert(False), "Unsupported estimate mode: {}".format(self.estimate_mode) 

        if self.loss_type == 'l1':
            loss_diff = torch.nn.functional.l1_loss(estimated, target.squeeze())

        elif self.loss_type == 'l2':
            loss_diff = torch.nn.functional.mse_loss(estimated, target.squeeze())
       
        return loss_diff, pred_x0#.detach() 
    
    def get_model_params(self):
        params = list(self.diffusion.parameters())
        return params

    def update(self):
        if self.use_ema:
            self.update_ema()

    def update_ema(self):
        self.ema_step += 1
        if self.ema_step % self.ema_update_rate == 0:
            if self.ema_step < self.ema_start:
                self.ema_diffusion.load_state_dict(self.diffusion.state_dict())
            else:
                self.ema.update_model_average(self.ema_diffusion, self.diffusion)


class GaussianDiffusion(nn.Module):
    __doc__ = r"""Gaussian Diffusion model. Forwarding through the module returns diffusion reversal scalar loss tensor.
    Input:
        x: tensor of shape (N, img_channels, *img_size)
        y: tensor of shape (N)
    Output:
        scalar loss tensor
    """
    def __init__(
        self,
        config
    ):
        super().__init__()

        self.T = config["diffusion"]['T']
        self.schedule_mode = config["diffusion"]["noise_schedule_mode"]
        self.estimate_mode = config["diffusion"]["estimate_mode"]
        self.norm_type = config["model_hyperparam"]["norm_type"]
        self.act_type = config["model_hyperparam"]["act_type"]
        self.time_emb_dim = config["model_hyperparam"]["time_emb_size"]
        self.input_text_emb_dim = config["model_hyperparam"]["input_text_emb_dim"]
        self.text_emb_dim = config["model_hyperparam"]["text_emb_size"]

        self.use_text_cfg = config["model_hyperparam"]["use_text_cfg"]
        self.text_cfg_scale = config["model_hyperparam"]["text_cfg_scale"]
        self.text_cfg_prob = config["model_hyperparam"]["text_cfg_prob"]

        self.use_last_frame_cfg = config["model_hyperparam"]["use_last_frame_cfg"]
        self.last_frame_cfg_scale = config["model_hyperparam"]["last_frame_cfg_scale"]
        self.last_frame_cfg_prob = config["model_hyperparam"]["last_frame_cfg_prob"]

        self.hidden_dim = config["model_hyperparam"]["hidden_size"]
        self.layer_num = config["model_hyperparam"]["layer_num"]
        self.frame_dim = config['frame_dim']
        
        self.model = NoiseDecoder(self.frame_dim, self.hidden_dim, self.text_emb_dim, self.time_emb_dim, self.layer_num, self.norm_type, self.act_type)
        self.time_mlp = torch.nn.Sequential(
            Embedding.PositionalEmbedding(self.time_emb_dim, 1.0),
            torch.nn.Linear(self.time_emb_dim, self.time_emb_dim),
            Activation.SiLU(),
            torch.nn.Linear(self.time_emb_dim, self.time_emb_dim),
        )

        self.cond_mlp = torch.nn.Sequential(
            torch.nn.Linear(self.input_text_emb_dim, self.text_emb_dim),
            Activation.SiLU(),
            torch.nn.Linear(self.text_emb_dim, self.text_emb_dim),
        )

        betas = self._generate_diffusion_schedule()
        alphas = 1. - betas
        alphas_cumprod = np.cumprod(alphas)
        to_torch = partial(torch.tensor, dtype=torch.float32)

        self.register_buffer("betas", to_torch(betas))
        self.register_buffer("alphas", to_torch(alphas))
        self.register_buffer("alphas_cumprod", to_torch(alphas_cumprod))

        self.register_buffer("sqrt_alphas_cumprod", to_torch(np.sqrt(alphas_cumprod)))
        self.register_buffer("sqrt_one_minus_alphas_cumprod", to_torch(np.sqrt(1. - alphas_cumprod)))
        self.register_buffer("reciprocal_sqrt_alphas", to_torch(np.sqrt(1. / alphas)))
        self.register_buffer("reciprocal_sqrt_alphas_cumprod", to_torch(np.sqrt(1. / alphas_cumprod)))
        self.register_buffer("reciprocal_sqrt_alphas_cumprod_m1", to_torch(np.sqrt(1. / alphas_cumprod -1)))
        self.register_buffer("remove_noise_coeff", to_torch(betas / np.sqrt(1. - alphas_cumprod)))
        self.register_buffer("sigma", to_torch(np.sqrt(betas)))


    def _generate_diffusion_schedule(self, s=0.008):
        def f(t, T):
            return (np.cos((t / T + s) / (1 + s) * np.pi / 2)) ** 2
        
        if self.schedule_mode == 'cosine':  
            # from https://arxiv.org/abs/2102.09672  
            alphas = []
            f0 = f(0, self.T)

            for t in range(self.T + 1):
                alphas.append(f(t, self.T) / f0)
            
            betas = []

            for t in range(1, self.T + 1):
                betas.append(min(1 - alphas[t] / alphas[t - 1], 0.999))
            return np.array(betas)
        
        elif self.schedule_mode == 'uniform':
            # from original ddpm paper
            beta_start = 0.0001
            beta_end = 0.02
            return np.linspace(beta_start, beta_end, self.T)
        
        elif self.schedule_mode == 'quadratic':
            beta_start = 0.0001
            beta_end = 0.02
            return np.linspace(beta_start**0.5, beta_end**0.5, self.T) ** 2
        
        elif self.schedule_mode == 'sigmoid':
            beta_start = 0.0001
            beta_end = 0.02
            betas = np.linspace(-6, 6, self.T)
            return 1/(1+np.exp(-betas)) * (beta_end - beta_start) + beta_start
        
        else:
            assert(False), "Unsupported diffusion schedule: {}".format(self.schedule_mode)
    

    @torch.no_grad()
    def extract(self, a, ts, x_shape):
        b, *_ = ts.shape
        out = a.gather(-1, ts)
        return out.reshape(b, *((1,) * (len(x_shape) - 1)))

    
    @torch.no_grad()
    def add_noise(self, x, ts):
        return x + self.extract(self.sigma, ts, x.shape) * torch.randn_like(x)
    
    def add_noise_w(self, x, ts, noise):
        return x + self.extract(self.sigma, ts, x.shape) * noise#torch.randn_like(x)

    @torch.no_grad()
    def compute_alpha(self, beta, ts):
        beta = torch.cat([torch.zeros(1).to(beta.device), beta], dim=0)
        a = (1 - beta).cumprod(dim=0).index_select(0, ts + 1).view(-1, 1)
        return a
    

    @torch.no_grad()
    def remove_noise(self, xt, pred, ts):
        output =  (xt - self.extract(self.remove_noise_coeff, ts, pred.shape) * pred) * \
                self.extract(self.reciprocal_sqrt_alphas, ts, pred.shape)
        
        return output
    
    def get_x0_from_xt(self, xt, ts, noise):
        output =  (xt - self.extract(self.sqrt_one_minus_alphas_cumprod, ts, xt.shape) * noise) * \
                self.extract(self.reciprocal_sqrt_alphas_cumprod, ts, xt.shape)
        return output

    def get_eps_from_x0(self, xt, ts, pred_x0):
        return (xt * self.extract(self.reciprocal_sqrt_alphas_cumprod, ts, xt.shape)  - pred_x0) / \
            self.extract(self.reciprocal_sqrt_alphas_cumprod_m1, ts, xt.shape)


    def perturb_x(self, x, ts, noise):
        return (
            self.extract(self.sqrt_alphas_cumprod, ts, x.shape) * x +
            self.extract(self.sqrt_one_minus_alphas_cumprod, ts, x.shape) * noise
        )   


    @torch.no_grad()
    def sample_ddpm_firstframe(self, num_init, extra_info, device):
        text_emb = torch.as_tensor(extra_info['text_embeddings'], device=device)
        text_emb = self.cond_mlp(text_emb)
        b = num_init

        text_emb = text_emb.tile((b,1))
        last_x = torch.zeros((b, self.frame_dim), device=device)
        x = torch.randn(b, self.frame_dim, device=device)

        for t in range(self.T - 1, -1, -1):
            ts = torch.tensor([t], device = last_x.device).repeat(b)
            te = self.time_mlp(ts)

            if self.use_text_cfg:
                last_x_expanded = last_x.tile((2,1))
                text_emb_expanded = text_emb.tile((2,1))

                x_expanded = x.tile((2,1))
                te_expanded = te.tile((2,1))
                
                if self.use_text_cfg:
                    text_emb_expanded[:b] *= 0
                
                pred = self.model(last_x_expanded, text_emb_expanded, x_expanded, te_expanded)
                pred_uncond, pred_cond = pred.chunk(2)

                pred =  (
                    pred_uncond 
                    + self.text_cfg_scale * (pred_cond - pred_uncond) 
                )

            else:
                pred = self.model(last_x, text_emb, x, te)

            if self.estimate_mode == 'epsilon':
                x = self.remove_noise(x, pred, ts)
            elif self.estimate_mode == 'x0':
                x = pred
            
            if t > 0:
                x = self.add_noise(x, ts)
        
        return x


    @torch.no_grad()
    def sample_ddpm(self, last_x, extra_info):
        b = last_x.shape[0]
        device = last_x.device
        dtype = last_x.dtype

        x = torch.randn(b, last_x.shape[-1]).to(device)
        text_emb = torch.as_tensor(extra_info['text_embeddings'], device=device, dtype=dtype)
        text_emb = self.cond_mlp(text_emb)
        text_emb = text_emb.tile((b,1))

        for t in range(self.T - 1, -1, -1):
            ts = torch.tensor([t], device = last_x.device).repeat(b)
            te = self.time_mlp(ts)

            if self.use_text_cfg or self.use_last_frame_cfg:

                last_x_expanded = last_x.tile((2,1))
                text_emb_expanded = text_emb.tile((2,1))
                x_expanded = x.tile((2,1))
                te_expanded = te.tile((2,1))
                
                if self.use_text_cfg:
                    text_emb_expanded[:b] *= 0
                
                if self.use_last_frame_cfg:
                    last_x_expanded[:b] *= 0

                pred = self.model(last_x_expanded, text_emb_expanded, x_expanded, te_expanded)
                pred_uncond, pred_cond = pred.chunk(2)

                pred =  (
                    pred_uncond 
                    + self.text_cfg_scale * (pred_cond - pred_uncond) 
                )

            else:
                pred = self.model(last_x, text_emb, x, te)


            if self.estimate_mode == 'epsilon':
                x = self.remove_noise(x, pred, ts)
            elif self.estimate_mode == 'x0':
                x = pred
            
            if t > 0:
                x = self.add_noise(x, ts)
        
        return x

    
    def sample_rl_ddpm(self, last_x, action_dict, extra_info):
        
        steps = extra_info['action_step']
        train_rand_scale =  extra_info['rand_scale']
        test_rand_scale = extra_info['test_rand_scale']
        clip_scale = extra_info['clip_scale']

        action_mode = extra_info['action_mode']
        is_train = extra_info['is_train']
        
        action_scale = extra_info['action_scale'] if is_train else extra_info['test_action_scale']

        action_dim_per_step = 8 if action_mode == 'loco' else self.frame_dim
        text_emb = self.cond_mlp(extra_info['text_embeddings'].to(last_x.device).float())

        x = action_dict[...,:action_dim_per_step] / 3
        for t in range(self.T - 1, -1, -1):
            with torch.no_grad():
                
                ts = torch.tensor([t], device = last_x.device).repeat(last_x.shape[0])
                te = self.time_mlp(ts)
                pred = self.model(last_x, text_emb, x, te).detach()
                
                if self.estimate_mode == 'epsilon':
                    x = self.remove_noise(x, pred, ts)
                elif self.estimate_mode == 'x0':
                    x = pred
            
            if t in steps:
                i = steps.index(t) + 1
                dx = action_dict[...,i*action_dim_per_step:(i+1)*action_dim_per_step] 
                rand_scale = train_rand_scale if is_train else test_rand_scale
                
                rand_scale *= torch.randn_like(dx) 

                x += action_scale * (dx + rand_scale * self.extract(self.sigma, ts, x.shape)[0])
                x = torch.clamp(x, -clip_scale, clip_scale)
               
            if t > 0:
                x = self.add_noise(x, ts)
        return x

    

    @torch.no_grad()
    def sample_ddpm_interactive(self, last_x, edited_mask, edited_data, extra_info):
        repaint_step = extra_info['repaint_step']
        interact_stop_step = extra_info['interact_stop_step']
        text_emb = self.cond_mlp(extra_info['text_embeddings'])
        edited_mask_inv = 1 - edited_mask

        x = torch.randn(last_x.shape[0], last_x.shape[-1]).to(last_x.device)
        
        for t in range(self.T - 1, -1, -1):
            for t_rp in range(repaint_step):
                ts = torch.tensor([t], device = last_x.device).repeat(last_x.shape[0])

                te = self.time_mlp(ts)
                pred = self.model(last_x, text_emb, x, te).detach()
                
                if self.estimate_mode == 'epsilon':
                    x = self.remove_noise(x, pred, ts)
                elif self.estimate_mode == 'x0':
                    x = pred
                
                cur_edited_mask_inv = edited_mask_inv.clone()
                if t > interact_stop_step:
                    #cur_edited_mask_inv = torch.randn_like(edited_mask_inv)
                    x = edited_data * edited_mask + x * cur_edited_mask_inv #x* cur_edited_mask_inv
               
                if t > 0:
                    #if t_rp < repaint_step and t != self.T-1 and t > interact_stop_step:
                    #    ts = torch.tensor([t+1], device = last_x.device).repeat(last_x.shape[0])
                    x = self.add_noise(x, ts)

        return x
    
    
    def forward(self, cur_x, next_x, ts, extra_info):
        bs = cur_x.shape[0]
        dtype = cur_x.dtype
        device = cur_x.device

        if ts is None:
            ts = torch.randint(0, self.T, (bs,), device=device)
        time_emb = self.time_mlp(ts) 

        noise = torch.randn_like(next_x)
        perturbed_x = self.perturb_x(next_x, ts.clone(), noise)
        
        text_emb = self.cond_mlp(extra_info['text_embeddings'])
        
        if self.use_text_cfg:
            masks = torch.ones((bs,1),device=device,dtype=dtype) * self.text_cfg_prob
            masks = 1 - torch.bernoulli(masks)
            text_emb = text_emb * masks
        
        if self.use_last_frame_cfg:
            masks = torch.ones((bs,1),device=device,dtype=dtype) * self.last_frame_cfg_prob
            masks = 1 - torch.bernoulli(masks)
            cur_x = cur_x * masks
        
        estimated = self.model(cur_x, text_emb, perturbed_x, time_emb)
        return estimated, noise, perturbed_x, ts


class NoiseDecoder(nn.Module):
    def __init__(
        self,
        frame_size,
        hidden_size,
        text_emb_size,
        time_emb_size,
        layer_num,
        norm_type,
        act_type
    ):
        super().__init__()

        self.input_size = frame_size
        layers = []
        for _ in range(layer_num): 
            if act_type == 'ReLU':
                non_linear = torch.nn.ReLU() ### v12 is ReLU
            elif act_type == 'SiLU':
                non_linear = Activation.SiLU() 
            linear = nn.Linear(hidden_size + frame_size * 2 + time_emb_size + text_emb_size, hidden_size)
            if norm_type == 'layer_norm':
                norm_layer = nn.LayerNorm(hidden_size)
            elif norm_type == 'group_norm':
                norm_layer = nn.GroupNorm(16, hidden_size)

            layers.append(norm_layer)
            layers.extend([non_linear, linear])
            
        self.net = nn.ModuleList(layers)
        self.fin = nn.Linear(frame_size * 2 + time_emb_size + text_emb_size, hidden_size)
        self.fco = nn.Linear(hidden_size + frame_size * 2  + time_emb_size + text_emb_size, frame_size)
        self.act = Activation.SiLU()
  
    def forward(self, xcur, text_emb, xnext, time_emb):
        
        x0 = xnext
        y0 = xcur
        x = torch.cat([xcur, text_emb, xnext, time_emb], dim=-1)
        x = self.fin(x)

        for i, layer in enumerate(self.net):
            if i % 3 == 2:
                x = torch.cat([x, text_emb, x0, y0, time_emb], dim=-1)
                x = layer(x)
            else:
                x = layer(x)

        x = torch.cat([x, text_emb, x0, y0, time_emb],dim=-1) 
        x = self.fco(x)
        return x 
   