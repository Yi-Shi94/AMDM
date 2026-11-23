import torch 
import torch.nn as nn
import math

class PositionalEmbedding(nn.Module):
    __doc__ = r"""Computes a positional embedding of timesteps.
    Input:
        x: tensor of shape (N)
    Output:
        tensor of shape (N, dim)
    Args:
        dim (int): embedding dimension
        scale (float): linear scale to be applied to timesteps. Default: 1.0
    """

    def __init__(self, dim, scale=1.0):
        super().__init__()
        assert dim % 2 == 0
        self.dim = dim
        self.scale = scale

    def forward(self, x):
        device = x.device
        half_dim = self.dim // 2
        emb = math.log(10000) / half_dim
        emb = torch.exp(torch.arange(half_dim, device=device) * -emb)
        emb = torch.outer(x * self.scale, emb)
        emb = torch.cat((emb.sin(), emb.cos()), dim=-1)
        return emb


class ActionEmbedding(nn.Module):
    def __init__(self,
                 num_actions,
                 latent_dim,
                 guidance_scale=7.5,
                 guidance_uncodp=0.1,
                 force_mask=False):
        super().__init__()
        self.nclasses = num_actions
        self.guidance_scale = guidance_scale
        self.action_embedding = nn.Parameter(
            torch.randn(num_actions, latent_dim))

        self.guidance_uncodp = guidance_uncodp
        self.force_mask = force_mask
        self._reset_parameters()

    def forward(self, input):
        #idx = input[:, 0].to(torch.long)  # an index array must be long
        idx = input.argmax(dim=1).long()
        output = self.action_embedding[idx]
        return output.float()
      
    def mask_cond(self, output, force=False):
        bs, d = output.shape
        # classifer guidence
        if self.force_mask or force:
            return torch.zeros_like(output)
        elif self.training and self.guidance_uncodp > 0.:
            mask = torch.bernoulli(
                torch.ones(bs, device=output.device) *
                self.guidance_uncodp).view(
                    bs, 1)  # 1-> use null_cond, 0-> use real cond
            return output * (1. - mask)
        else:
            return output

    def _reset_parameters(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)
