import glob
import os
import shutil
import ffmpy
import torch
import numpy as np
import tqdm

import model.model_builder as model_builder
import model.trainer_builder as trainer_builder
import dataset.dataset_builder as dataset_builder
import os.path as osp
import dataset.util.unit as unit_util
import dataset.util.bvh as bvh_util
import dataset.util.humanml3d.script.motion_process as motion_process
import render.smpl.vis_utils as vis_utils


def gen_render(model_path, model_name, start_index, num_trial=20,step_default=360):
    
    model_config_file = 'config/model/amdm_humanml3d.yaml'
    #input_path = 'data/LAFAN1_tpose_dance/dance2_subject5.bvh'
    #start_index = 100 #38044 #34858 + 3186 
    model_file = osp.join(model_path, model_name)
    data_mode = 'position' #position,velocity
    device = 'cuda'

    #out_path = 'output/base/amdm_humanml3d_large/init{}'.format(start_index)
    out_path = '{}/init{}'.format(model_path, start_index)
    os.makedirs(out_path, exist_ok=True)

    trainer = trainer_builder.build_trainer(model_config_file,device)
    model = model_builder.build_model(model_config_file, trainer.dataset, device)

    #dataset = dataset_builder.build_dataset(model_config_file,device)
    #end_offset = 450 #style100:450, amass:1 lafan:0
    #start_offset = 400 #style00:400, amass:0, lafan_small: 0

    #for fn, vr in zip(trainer.dataset.file_lst, trainer.dataset.valid_range):   
    #   print(fn, vr)
        #print(trainer.dataset.valid_range)

    model = torch.load(model_file)
    model.to(device)
    model.eval()
    #normed_data = trainer.dataset.load_new_data(input_path)

    normed_data = trainer.dataset.motion_flattened
    start_x = torch.tensor(normed_data[start_index]).to(device).float()

    gen_seq = model.eval_seq(start_x, None, step_default, num_trial)
    nan_mask = ~torch.isnan(gen_seq)
    nan_mask = nan_mask.prod(dim=-1)
    nan_mask = torch.cumsum(nan_mask, dim=-1)
    nan_mask = torch.max(nan_mask, dim=-1)[0]
    print('nan_idx:',nan_mask)

    all_motions = []
    all_lengths = []
    for i in range(gen_seq.shape[0]):
        seq = torch.cat([start_x[None,...], gen_seq[i]])
        try:
            seq = trainer.dataset.denorm_data(seq, device=device).detach().cpu().numpy()
            jnts_lst = trainer.dataset.x_to_jnts(seq)
            all_motions.append(jnts_lst.transpose(1,2,0)[None,...])
            all_lengths.append(step_default)

            print('filename',osp.join(out_path,'{}'.format(i)))
            #jnts_lst = np.array(jnts_lst)
            trainer.dataset.plot_jnts(jnts_lst, osp.join(out_path,'{}'.format(i)))
            if os.path.isfile(osp.join(out_path,'{}'.format(i))+'.mp4'):
                os.remove(osp.join(out_path,'{}'.format(i))+'.mp4')
            ff = ffmpy.FFmpeg(
                inputs={osp.join(out_path,'{}'.format(i))+'.gif': None},
                outputs={osp.join(out_path,'{}'.format(i))+'.mp4': "-filter:v fps=30"})
            ff.run()
            os.remove(osp.join(out_path,'{}'.format(i))+'.gif')
        except:
            print('skip')

    # After concat -> [r1_dstep_1, r2_dstep_1, r3_dstep_1, r1_dstep_2, r2_dstep_2, ....]
    all_motions = np.concatenate(all_motions,
                                    axis=0)  # [bs * num_dump_step, 1, 3, 120]
    print(all_motions.shape)
    all_lengths = np.array(all_lengths)

    npy_path = os.path.join(out_path, 'results.npy')
    print(f"saving results file to [{npy_path}]")
    np.save(
        npy_path, {
            'motion': all_motions,
            'text': ['dummy' for _ in range(len(all_lengths))],
            'lengths': all_lengths,
            'num_samples': 1,
            'num_repetitions': 1
        })
    #for i in range(all_motions.shape[0]):
    #    renderf(npy_path, out_path, i)
    return all_motions

def renderf(input_npy, out_path, idx):
    #np_f = np.load(input_npy,allow_pickle=True)
    #num_file = np_f['arr_0']['motion'].shape[0]
    

    out_npy_path = osp.join(out_path,'{}'.format(idx)+'.npy')
    results_dir = osp.join(out_path,'{}'.format(idx))

    if os.path.exists(results_dir):
        shutil.rmtree(results_dir)

    os.makedirs(results_dir)
    os.makedirs(os.path.join(results_dir, "loc"))

    npy2obj = vis_utils.npy2obj(input_npy, idx, 0,
                                device=0, cuda=True)

    print('Saving obj files to [{}]'.format(os.path.abspath(results_dir)))
    for frame_i in tqdm.tqdm(range(npy2obj.real_num_frames)):
        npy2obj.save_obj(os.path.join(results_dir, 'frame{:03d}.obj'.format(frame_i)), frame_i)

    print('Saving SMPL params to [{}]'.format(os.path.abspath(out_npy_path)))
    npy2obj.save_npy(out_npy_path)

        
if __name__ == "__main__":
   
    model_path = 'output/base/amdm_humanml3d_contx2_large/'
    model_name = 'model.pt'
    start_index = 108991#170005 ##38044 ##10714 + 3186 #in humor unclear
    num_trial = 5
    step = 3000
    #gen_render(model_path, model_name, start_index, num_trial, step)

    input_path = '{}/init{}/results.npy'.format(model_path, start_index)
    out_path = '{}/init{}/'.format(model_path, start_index)
    #lst = [3,5] #,3,5,6,8,9]

    for i in range(10,15):
        renderf(input_path, out_path, i)



