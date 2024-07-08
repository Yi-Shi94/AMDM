import torch.nn as nn
import torch
from policy.common.controller import init, DiagGaussian_adaptive, DiagGaussian_fixed

def init_weights(m):
    if isinstance(m, nn.Linear):
        torch.nn.init.zero_(m.weight)
        torch.nn.init.zero_(m.bias)
    

class PPOModel(nn.Module):
    NAME = 'PPO'
    def __init__(self, config, env, device):
        super().__init__()

        self.actor = ActorNet(env).to(device)
        self.critic = CriticNet(env).to(device)
        init_weights(self.actor) 
        #self.w = torch.nn.Parameter(torch.ones(1,requires_grad=True).to(device)*0.15) 
        
        
        self.distr_type = config['distr_type']
        self.std_value = config.get('distr_std',0.3)

        if self.distr_type == 'fixed':
            self.dist = DiagGaussian_fixed(self.std_value)
        elif self.distr_type == 'adaptive':
            self.dist = DiagGaussian_adaptive(self.actor.action_dim)
        
        self.state_size = 1

    def forward(self, inputs):
        raise NotImplementedError

    def act(self, inputs, deterministic=False):
        action = self.actor(inputs)
        #action = action * torch.min(self.w, 1.0)
        dist = self.dist(action)

        if deterministic:
            action = dist.mode()

        else:
            action = dist.sample() 
            action.clamp_(-1.0, 1.0)

        action_log_probs = dist.log_probs(action)
        value = self.critic(inputs)

        return value, action, action_log_probs

    def get_value(self, inputs):
        value = self.critic(inputs)
        return value

    def evaluate_actions(self, inputs, action):
        value = self.critic(inputs)
        mode = self.actor(inputs)
        #mode = mode * torch.min(self.w, 1.0)
        dist = self.dist(mode)

        action_log_probs = dist.log_probs(action)
        dist_entropy = dist.entropy().mean()

        return value, action_log_probs, dist_entropy


class CriticNet(nn.Module):
    def __init__(self, env):
        super().__init__()

        self.observation_dim = env.observation_space.shape[0]
        h_size = 256
        self.critic = nn.Sequential(
                nn.Linear(self.observation_dim, h_size),
                nn.ReLU(),
                nn.Linear(h_size, h_size),
                nn.ReLU(),
                nn.Linear(h_size, h_size),
                nn.ReLU(),
                nn.Linear(h_size, 1)
            )
        

    def forward(self, x):
        return self.critic(x)



class ActorNet(nn.Module):
    def __init__(self, env):
        super().__init__()

        self.observation_dim = env.observation_space.shape[0]
        self.action_dim = env.action_space.shape[0]

        h_size = 256
        self.actor = nn.Sequential(
            nn.Linear(self.observation_dim, h_size),
            nn.ReLU(),
            nn.Linear(h_size, h_size),
            nn.ReLU(),
            nn.Linear(h_size, h_size),
            nn.ReLU(),
            nn.Linear(h_size, self.action_dim),
            nn.Tanh()
        )
    def forward(self, x):
        return self.actor(x)


