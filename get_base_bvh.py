import os
import torch
import numpy as np
import dataset.dataset_builder as dataset_builder
import os.path as osp
import dataset.util.unit as unit_util
import dataset.util.bvh as bvh_util
import model.model_builder as model_builder
import ffmpy

#model_file = 'output/base/amdm_lafan1_new_4_conti3_full/model.pt'
#start_index = 100 #38044 #34858 + 3186 
#start_index = 44480 #different step 44480 ##cartwheel38044 ##10714 + 3186 #in humor unclear

start_index = 1000 # 38046 #38046 #163136+208#sprint intro79552 + 1308 #141243 #257692 #35900#13900 #38044 #71800 #21200 #71730
step_default = 120

par_path = 'output/base/'
model_name = 'amdm_lafan1_25s_eps'
model_config_file = 'config/model/amdm_lafan1_subj5.yaml'

state_dict = torch.load('{}/{}/model_param.pth'.format(par_path,model_name))
out_path = '{}/{}/{}_{}step_intro'.format(par_path, model_name, start_index, step_default)  #'output/base/amdm_lafan1_fcc4_cont1/{}_{}step_intro'.format(start_index, step_default) #72040->71800


os.makedirs(out_path, exist_ok=True)

num_trial_default = 10 #as humor
data_mode = 'angle' #position,velocity
device = 'cuda'

root_offset = np.array([0,0,0]) #1200

dataset = dataset_builder.build_dataset(model_config_file,device)
#for fn, vr in zip(dataset.file_lst, dataset.valid_range):   
#    print(fn, vr)

model = model_builder.build_model(model_config_file, dataset, device)
model.load_state_dict(state_dict)


model.to(device)
model.eval()

#start_index = self.valid_idx[start_index]
#normed_data = trainer.dataset.load_new_data(input_path)

output_unit = 'cm'
unit_scale_inv = 1.0/unit_util.unit_conver_scale(dataset.unit)
offset = dataset.joint_offset * unit_scale_inv

normed_data = dataset.motion_flattened
start_x = torch.tensor(normed_data[start_index]).to(device).float()

gen_seq = model.eval_seq(start_x, None, step_default, num_trial_default)
nan_mask = ~torch.isnan(gen_seq)
nan_mask = nan_mask.prod(dim=-1)
nan_mask = torch.cumsum(nan_mask, dim=-1)
nan_mask = torch.max(nan_mask, dim=-1)[0]
print('nan_idx:',nan_mask)
all_seq_lst = []

############ plot_gt ###########
gt = dataset.denorm_data(normed_data[start_index:start_index+step_default+1])
jnts_lst =[]
for mode in dataset.data_component:
    jnts = dataset.x_to_jnts(gt, mode)
    jnts_lst.append(jnts)
    if data_mode == mode:
        all_seq_lst.append(jnts)

print('filename',osp.join(out_path,'{}'.format('gt')))
jnts_lst = np.array(jnts_lst)
dataset.plot_jnts(jnts_lst, osp.join(out_path,'{}'.format('gt')))
if os.path.isfile(osp.join(out_path,'{}'.format('gt'))+'.mp4'):
    os.remove(osp.join(out_path,'{}'.format('gt'))+'.mp4')
ff = ffmpy.FFmpeg(
    inputs={osp.join(out_path,'{}'.format('gt'))+'.gif': None},
    outputs={osp.join(out_path,'{}'.format('gt'))+'.mp4': "-filter:v fps=30"})
ff.run()
os.remove(osp.join(out_path,'{}'.format('gt'))+'.gif')

xyzs_seq, euler_angle = dataset.x_to_rotation(gt, 'angle')
xyzs_seq = xyzs_seq * unit_scale_inv
xyzs_seq = root_offset[None,...] + xyzs_seq
bvh_util.output_as_bvh(osp.join(out_path,'{}.bvh'.format('gt')),xyzs_seq, euler_angle, dataset.rotate_order,
                        dataset.joint_names, dataset.joint_parent, offset, dataset.fps) 

root_xzs = xyzs_seq[:,[0,2]]
np.save('traj_{}.npy'.format('gt'), root_xzs) 


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
        print('filename',osp.join(out_path,'{}'.format(i)))
        jnts_lst = np.array(jnts_lst)
        dataset.plot_jnts(jnts_lst, osp.join(out_path,'{}'.format(i)))
        if os.path.isfile(osp.join(out_path,'{}'.format(i))+'.mp4'):
            os.remove(osp.join(out_path,'{}'.format(i))+'.mp4')
        ff = ffmpy.FFmpeg(
        inputs={osp.join(out_path,'{}'.format(i))+'.gif': None},
        outputs={osp.join(out_path,'{}'.format(i))+'.mp4': "-filter:v fps=30"})
        ff.run()
        os.remove(osp.join(out_path,'{}'.format(i))+'.gif')
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

print(all_seq_lst[0].shape,all_seq_lst[1].shape)
dataset.plot_traj(np.array(all_seq_lst), osp.join(out_path,'traj.png'))