import os
import torch
import numpy as np
import dataset.dataset_builder as dataset_builder
import os.path as osp
import dataset.util.unit as unit_util
import dataset.util.bvh as bvh_util
import model.model_builder as model_builder

def gen_bvh(model_config_file, model_state_path, out_path, data_file_name, start_frame_index, num_trial_default, step_default, device = 'cuda'):

    os.makedirs(out_path, exist_ok=True)
    data_mode = 'angle' #position,velocity
    root_offset = np.array([0,0,0]) #1200

    dataset = dataset_builder.build_dataset(model_config_file, load_full_dataset=False)

    model = model_builder.build_model(model_config_file, dataset, device)
    model.load_state_dict(model_state_path)

    model.to(device)
    model.eval()

    unit_scale_inv = 1.0 / unit_util.unit_conver_scale(dataset.unit)
    offset = dataset.joint_offset * unit_scale_inv

    normed_data = dataset.load_new_data(data_file_name)
    
    start_x = torch.tensor(normed_data[start_frame_index]).to(device).float()

    gen_seq = model.eval_seq(start_x, None, step_default, num_trial_default)
    nan_mask = ~torch.isnan(gen_seq)
    nan_mask = nan_mask.prod(dim=-1)
    nan_mask = torch.cumsum(nan_mask, dim=-1)
    nan_mask = torch.max(nan_mask, dim=-1)[0]
    print('not_nan_num:',nan_mask)
    all_seq_lst = []

    ############ plot_gt ###########
   
    ############ plot_gen ###########
    for i in range(gen_seq.shape[0]):
        
        seq = torch.cat([start_x[None,...], gen_seq[i]])
        seq = dataset.denorm_data(seq, device=device).detach().cpu().numpy()
        jnts_lst = []#trainer.dataset.x_to_jnts(seq, data_mode)
        
        for mode in dataset.data_component:
            jnts = dataset.x_to_jnts(seq, mode)
            jnts_lst.append(jnts)
            if data_mode == mode:
                all_seq_lst.append(jnts)
        try:
            pass
        except:
            print('Failed/Canceled')
            continue 
        xyzs_seq, euler_angle = dataset.x_to_rotation(seq, 'angle')
        xyzs_seq = xyzs_seq * unit_scale_inv
        xyzs_seq = root_offset[None,...] + xyzs_seq
        bvh_util.output_as_bvh(osp.join(out_path,'{}.bvh'.format(i)),xyzs_seq, euler_angle, dataset.rotate_order,
                            dataset.joint_names, dataset.joint_parent, offset, dataset.fps) 
        
        root_xzs = xyzs_seq[:,[0,2]]
        np.save(osp.join(out_path,'traj_{}.npy'.format(i)), root_xzs)

    dataset.plot_traj(np.array(all_seq_lst), osp.join(out_path,'traj.png'))

if __name__ == '__main__':
    #data_file_name = './data/100STYLE/Depressed/Depressed_BW.bvh'
    #start_index = 322 #   
    
    data_file_name = 'data/LAFAN1_tpose/dance1_subject1.bvh'
    start_index = 3188 #cartwheel

    step_default = 400
    num_trial_default = 5
    model_name = 'amdm_lafan1'

    
    par_path = 'output/base/'
    model_config_file = '{}/{}/config.yaml'.format(par_path, model_name)
   

    state_dict = torch.load('{}/{}/model_param2.pth'.format(par_path,model_name))
    out_path = '{}/{}/{}_{}step_intro'.format(par_path, model_name, start_index, step_default)  
    
    
    gen_bvh(model_config_file, state_dict, out_path, data_file_name, start_index, num_trial_default, step_default)