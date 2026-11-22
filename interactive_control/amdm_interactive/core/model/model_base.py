import numpy as np
import abc
import torch

class BaseModel(torch.nn.Module):
    def __init__(self, config, dataset, device):
        super().__init__()
        self.config = config
        self.device = device
        self.joint_parent = dataset.joint_parent
        self.joint_offset = dataset.joint_offset

        return
        
    @abc.abstractmethod
    def _build_model(self, config):
        return

    @abc.abstractmethod
    def eval_step(self, cur_x, extra_dict):
        return

    @abc.abstractmethod
    def compute_loss(self, cur_x, tar_x, extra_dict):
        return
