import warnings
warnings.filterwarnings("ignore")

import os
import sys
import shutil
import torch
import numpy as np

import dataset.dataset_builder as dataset_builder
import model.model_builder as model_builder
import model.trainer_builder as trainer_builder
import policy.envs.env_builder as env_builder
import policy.learning.agent_builder as agent_builder

from policy.common.misc_utils import EpisodeRunner
import util.arg_parser as arg_parser
import util.rand_util as rand_util
import util.mp_util as mp_util

def set_np_formatting():
    np.set_printoptions(edgeitems=30, infstr='inf',
                        linewidth=4000, nanstr='nan', precision=2,
                        suppress=False, threshold=10000, formatter=None)
    return

def load_args(argv):
    args = arg_parser.ArgParser()
    args.load_args(argv[1:])

    arg_file = args.parse_string("arg_file", "")
    if (arg_file != ""):
        succ = args.load_file(arg_file)
        assert succ, print("Failed to load args from: " + arg_file)

    rand_seed_key = "rand_seed"
    if (args.has_key(rand_seed_key)):
        rand_seed = args.parse_int(rand_seed_key)
        #rand_seed = mp_util.get_proc_rank()
        rand_util.set_rand_seed(rand_seed)
    return args


def build_trainer(config, device):
    trainer = trainer_builder.build_trainer(config, device)
    return trainer

def build_model(config, dataset, device):
    model = model_builder.build_model(config, dataset, device)
    return model

def build_dataset(config, device):
    dataset = dataset_builder.build_dataset(config, device)
    return dataset

def build_agent(config, model, env, device):
    agent = agent_builder.build_agent(config, model, env, device)
    return agent

def build_env(config, int_output_dir, model, dataset, mode, device):
    env = env_builder.build_envs(config, int_output_dir, model, dataset, mode, device)
    return env

def train(agent, out_model_file, int_output_dir):
    agent.train_controller(out_model_file=out_model_file, 
                      int_output_dir=int_output_dir)
    return

def test(agent):
    agent.test_controller()
    return 

def evaluate(agent):
    agent.evaluate_controller()
    return 

def test_no_agent(env):
    seed_n = 0

    env.reset()
    env.seed(seed_n)

    torch.manual_seed(seed_n)
    torch.cuda.manual_seed(seed_n)
    
    env.reset_initial_frames()
    with EpisodeRunner(env) as runner:
        while not runner.done:
            frame = env.get_next_frame()
            for i in range(env.frame_skip):
                _, reward, done, info = env.calc_env_state(frame)

                if done.any():
                    reset_indices = env.parallel_ind_buf.masked_select(done.squeeze())
                    env.reset_index(reset_indices)
                #try:
                #    if info.get("reset").all():
                #        env.reset()
                #except:
                #    if info.get("reset"):
                #        env.reset()
    return      


def create_output_dirs(out_model_file, int_output_dir):
    if (mp_util.is_root_proc()):
        output_dir = os.path.dirname(out_model_file)
        if (output_dir != "" and (not os.path.exists(output_dir))):
            os.makedirs(output_dir, exist_ok=True)
        
        if (int_output_dir != "" and (not os.path.exists(int_output_dir))):
            os.makedirs(int_output_dir, exist_ok=True)
    return

def copy_config_file(config_file, output_dir):
    out_file = os.path.join(output_dir, os.path.basename(config_file))
    shutil.copy(config_file, out_file)
    return


            
def run(rank, num_procs, args):
    mode = args.parse_string("mode", "train")
    device = args.parse_string("device", 'cuda:0')
    log_file = args.parse_string("log_file", "")
    out_model_file = args.parse_string("out_model_file", "")
    trained_model_path = args.parse_string("model_path", "")
    int_output_dir = args.parse_string("int_output_dir", "")
    master_port = args.parse_string("master_port", "")
    env_config_file = args.parse_string("env_config", "")
    model_config_file = args.parse_string("model_config", "")
    agent_config_file = args.parse_string("agent_config", "")
    trained_controller_path = args.parse_string("controller_path", "")
    mp_util.init(rank, num_procs, device, master_port)

    set_np_formatting()
    #if out_model_file is not None and int_output_dir is not None:
    create_output_dirs(out_model_file, int_output_dir)
    out_model_dir = os.path.dirname(out_model_file)
    
    dataset = build_dataset(model_config_file, device)
    
    if trained_model_path:
        try:
            model = model_builder.build_model(model_config_file, dataset, device)
            state_dict = torch.load(trained_model_path)
            model.load_state_dict(state_dict)
        except:
            model = torch.load(trained_model_path)
        
        model.to(device)
        model.eval()
    else:
        model = None

    if agent_config_file:
        env = build_env(env_config_file, int_output_dir, model, dataset, mode, device)
        agent = build_agent(agent_config_file, model, env, device)
        if trained_controller_path:
            print("Loading controller:",trained_controller_path)
            
            try:
                actor_critic = agent.actor_critic
                state_dict = torch.load(trained_controller_path)
                actor_critic.load_state_dict(state_dict)
            except:
                actor_critic = torch.load(trained_controller_path)
        

            actor_critic.to(device)
            actor_critic.eval()
            agent.actor_critic = actor_critic
    else:   
        env = build_env(env_config_file, int_output_dir, model, dataset, 'test', device)
        agent = None

    if (mode == "train"):
        assert agent is not None, "require a controller & a agent"
        copy_config_file(agent_config_file, out_model_dir)
        copy_config_file(env_config_file, out_model_dir)
        copy_config_file(model_config_file, out_model_dir)
        train(agent, out_model_file=out_model_file, int_output_dir=int_output_dir)
   
    elif (mode == "test"):
        if agent is None:
            print('agent is None, test no agent')
            test_no_agent(env)
        else:
            test(agent)

    elif (mode == "eval"):
        evaluate(agent)

    else:
        assert(False), "Unsupported mode: {}".format(mode)

    return

def main(argv):
    args = load_args(argv)
    num_workers = args.parse_int("num_workers", 1)
    assert(num_workers > 0)

    torch.multiprocessing.set_start_method("spawn")

    processes = []
    for i in range(num_workers - 1):
        rank = i + 1
        proc = torch.multiprocessing.Process(target=run, args=[rank, num_workers, args])
        proc.start()
        processes.append(proc)

    run(0, num_workers, args)

    for proc in processes:
        proc.join()
       
    return

if __name__ == "__main__":
    main(sys.argv)
