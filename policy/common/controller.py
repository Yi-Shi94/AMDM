import torch
import torch.nn as nn
import math
# Normal
FixedNormal = torch.distributions.Normal

log_prob_normal = FixedNormal.log_prob
FixedNormal.log_probs = lambda self, actions: log_prob_normal(self, actions).sum(
    -1, keepdim=True
)

normal_entropy = FixedNormal.entropy
FixedNormal.entropy = lambda self: normal_entropy(self).sum(-1)

FixedNormal.mode = lambda self: self.mean


def init(module, weight_init, bias_init, gain=1):
    weight_init(module.weight.data, gain=gain)
    bias_init(module.bias.data)
    return module


class AddBias(nn.Module):
    def __init__(self, bias):
        super(AddBias, self).__init__()
        self._bias =  nn.Parameter(bias.unsqueeze(1)) #torch.ones_like(bias, requires_grad=False) * 1  # #torch.ones_like(bias, requires_grad=False) * 1 #math.log(1)#nn.Parameter(bias.unsqueeze(1))

    def forward(self, x):
        if x.dim() == 2:
            bias = self._bias.t().view(1, -1)
        else:
            bias = self._bias.t().view(1, -1, 1, 1)
        return x + bias.to(x.device)


class DiagGaussian_adaptive(nn.Module):
    def __init__(self, num_outputs):
        super(DiagGaussian_adaptive, self).__init__()
        self.logstd = AddBias(torch.zeros(num_outputs))

    def forward(self, action_mean):
        #  An ugly hack for my KFAC implementation.
        zeros = torch.zeros(action_mean.size())
        if action_mean.is_cuda:
            zeros = zeros.cuda()

        action_logstd = self.logstd(zeros)
        return FixedNormal(action_mean, 0.3 * torch.ones_like(action_mean))


class DiagGaussian_fixed(nn.Module):
    def __init__(self, std):
        super(DiagGaussian_fixed, self).__init__()
        self.std = std

    def forward(self, action_mean):
        return FixedNormal(action_mean, self.std * torch.ones_like(action_mean))