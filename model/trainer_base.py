import abc
import copy
import numpy as np

import torch
import torch.nn.functional as F
import torch.optim as optim

from torch.utils.data import DataLoader

import util.eval as eval_util
import util.vis_util as vis_util
import util.logging as logging_util
import util.save as save_util

class BaseTrainer():
    def __init__(self, config, dataset, device):
        self.config = config
        self.device = device
        self.dataset = dataset

        optimizer_config = config['optimizer']
        self.batch_size = optimizer_config['mini_batch_size']
        self.num_rollout = optimizer_config['rollout']
        self.initial_lr = optimizer_config['initial_lr']
        self.final_lr = optimizer_config['final_lr']
        self.peak_student_rate = optimizer_config.get('peak_student_rate',1.0)
        self._get_schedule_samp_routines(config['optimizer'])
        
        test_config = config['test']
        self.test_interval = test_config["test_interval"]
        self.test_num_steps = test_config["test_num_steps"]
        self.test_num_trials = test_config["test_num_trials"]
        
        self.frame_dim = dataset.frame_dim
        self.train_dataloader = DataLoader(dataset=dataset, batch_size=self.batch_size, shuffle=True, drop_last=True)
        self.logger =  logging_util.wandbLogger(proj_name="{}_{}".format(self.NAME,dataset.NAME), run_name=self.NAME)

        self.plot_jnts_fn = self.dataset.plot_jnts if hasattr(self.dataset, 'plot_jnts') and callable(self.dataset.plot_jnts) \
                                                        else vis_util.vis_skel

        self.plot_traj_fn = self.dataset.plot_traj if hasattr(self.dataset, 'plot_traj') and callable(self.dataset.plot_traj) \
                                                        else vis_util.vis_traj
        return

    @abc.abstractmethod
    def train_loop(self, model):
        return    

    def _init_optimizer(self, model):
        self.optimizer = optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=self.initial_lr)

    def _update_lr_schedule(self, optimizer, epoch):
        """Decreases the learning rate linearly"""
        lr = self.initial_lr - (self.initial_lr - self.final_lr) * epoch / float(self.total_epochs)
        for param_group in optimizer.param_groups:
            param_group["lr"] = lr

    def _get_schedule_samp_routines(self, optimizer_config):
        self.anneal_times = optimizer_config['anneal_times']
        self.initial_teacher_epochs = optimizer_config.get('initial_teacher_epochs',1)
        self.end_teacher_epochs = optimizer_config.get('end_teacher_epochs',1)
        self.teacher_epochs = optimizer_config['teacher_epochs']
        self.ramping_epochs = optimizer_config['ramping_epochs']
        self.student_epochs = optimizer_config['student_epochs']
        self.use_schedule_samp = self.ramping_epochs != 0 or self.student_epochs != 0
        
        self.initial_schedule = torch.zeros(self.initial_teacher_epochs)
        self.end_schedule = torch.zeros(self.end_teacher_epochs)
        self.sample_schedule = torch.cat([ 
                # First part is pure teacher forcing
                torch.zeros(self.teacher_epochs),
                # Second part with schedule sampling
                torch.linspace(0.0, self.peak_student_rate, self.ramping_epochs),
                # last part is pure student
                torch.ones(self.student_epochs) * self.peak_student_rate,

        ])
        self.sample_schedule = torch.cat([self.sample_schedule  for _ in range(self.anneal_times)], axis=-1)
        self.sample_schedule = torch.cat([self.initial_schedule, self.sample_schedule, self.end_schedule])
       
        self.total_epochs = self.sample_schedule.shape[0]+1


    def train_model(self, model, out_model_file, int_output_dir, log_file):
        self._init_optimizer(model)
        for ep in range(0, self.total_epochs+1):
            loss_stats = self.train_loop(ep, model)

            if ep % self.test_interval == 0:
                if ep == 0:
                    continue
                save_util.save_weight(model, int_output_dir+'_ep{}.pth'.format(ep))
                save_util.save_weight(model, out_model_file)
                
            self.logger.log_epoch(loss_stats)
            self.logger.print_log(loss_stats)
            

