import yaml
import gymnasium as gym
from gymnasium.envs.registration import register, registry

import policy.envs.vis_env as vis_env
import policy.envs.randomplay_env as randomplay_env
import policy.envs.target_env as target_env
#import policy.envs.joystick_env as joystick_env
#import policy.envs.path_env as path_env

def build_envs(config_file, int_output_dir, model, dataset, mode, device):
    config = load_yaml_file(config_file)
    env_module = config["env_module"]
    env_name = config["env_name"]
    config['int_output_dir']  = int_output_dir
    seed = config.get("seed",0)
    if mode == 'test':
        config['is_rendered'] = True
        config['num_parallel'] = config.get('num_parallel_test',1)
    else:
        config['is_rendered'] = False
    
    print("Building {}-{}".format(env_module,env_name))

    gym.envs.registration.register(id= env_name, entry_point=env_module)

    env = gym.make(env_module, config=config, model=model, dataset=dataset, device=device)
    env.seed(seed)
    return env

def load_yaml_file(file):
    with open(file, "r") as stream:
        config = yaml.safe_load(stream)
    return config
