
import warnings
warnings.filterwarnings("ignore")

import os
os.environ['WANDB_API_KEY']='d2693de8bbe1184bdfd9703d7433fe3078232f18'
os.environ['WANDB_ENTITY']='sy3'
import sys
import shutil
import torch
import numpy as np

import dataset.dataset_builder as dataset_builder
import model.model_builder as model_builder
import model.trainer_builder as trainer_builder

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
        rand_seed = args.parse_string(rand_seed_key)
        rand_seed = int(rand_seed)
        print('rand seed',rand_seed)
        rand_util.set_rand_seed(rand_seed)
    return args

def build_model(config, dataset, device):
    model = model_builder.build_model(config, dataset, device)
    return model

def build_trainer(config, device):
    trainer = trainer_builder.build_trainer(config,device)
    return trainer

def train(trainer, model, out_model_file, int_output_dir, log_file):
    trainer.train_model(model, out_model_file=out_model_file, 
                      int_output_dir=int_output_dir, log_file=log_file)
    return

def build_dataset(config, device):
    dataset = dataset_builder.build_dataset(config, device)
    return dataset

def evaluate(trainer, model):
    result = trainer.evaluate_offline(model)
    return result

def create_output_dirs(out_model_file, int_output_dir):
    if (mp_util.is_root_proc()):
        output_dir = os.path.dirname(out_model_file)
        if (output_dir != "" and (not os.path.exists(output_dir))):
            os.makedirs(output_dir, exist_ok=True)
        
        if (int_output_dir != "" and (not os.path.exists(int_output_dir))):
            os.makedirs(int_output_dir, exist_ok=True)
    return

def copy_config_file(config_file, output_dir):
    out_file = os.path.join(output_dir, "config.yaml")
    shutil.copy(config_file, out_file)
    return

def run(rank, num_procs, args):
    mode = args.parse_string("mode", "train")
    device = args.parse_string("device", "cuda:0")
    log_file = args.parse_string("log_file", "")
    out_model_file = args.parse_string("out_model_file", "")
    trained_model_path = args.parse_string("model_path", "")
    
    int_output_dir = args.parse_string("int_output_dir", "")
    master_port = args.parse_string("master_port", "")
    model_config_file = args.parse_string("model_config", "")

    mp_util.init(rank, num_procs, device, master_port)

    set_np_formatting()
    create_output_dirs(out_model_file, int_output_dir)
    out_model_dir = os.path.dirname(out_model_file)
    
    trainer = build_trainer(model_config_file, device)
    model = build_model(model_config_file, trainer.dataset, device)
    dataset = build_dataset(model_config_file, device)
    if (trained_model_path != ""):
        try:
            model = model_builder.build_model(model_config_file, dataset, device)
            state_dict = torch.load(trained_model_path)
            model.load_state_dict(state_dict)
        except:
            model = torch.load(trained_model_path)
        
        model.to(device)
        model.eval()
        
    if (mode == "train"):
        copy_config_file(model_config_file, out_model_dir)
        train(trainer, model, out_model_file=out_model_file, 
              int_output_dir=int_output_dir, log_file=log_file)
            
    elif (mode == "eval"):
        stats = evaluate(trainer, model, device=device)
        return stats
    
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
