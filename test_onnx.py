import onnx
import onnxruntime as ort
import numpy as np

import torch
import torch.nn as nn

import model.model_builder as model_builder
import dataset.dataset_builder as dataset_builder

device = 'cpu'

model_path = 'output/base/amdm_lafan1_new_4_conti3_full'
model_config_file = 'config/model/amdm_lafan1_subj5.yaml'

dataset = dataset_builder.build_dataset(model_config_file, device=device)
onnx_model = onnx.load("my_simple_model.onnx")
onnx.checker.check_model(onnx_model)

ort_sess = ort.InferenceSession('my_simple_model.onnx')

idx = 1200
length = 300
T = 25

last_frame = dataset.motion_flattened[idx][None,...].astype(np.float32)


gt_seq = dataset.motion_flattened[idx:idx+length]
gt_seq = dataset.denorm_data(gt_seq)
dataset.plot_jnts_single(dataset.x_to_jnts(gt_seq, 'position'))


#############
gen_seq = torch.zeros(length, last_frame.shape[-1])
state_dict = torch.load('{}/model_weights_new_test.pth'.format(model_path))
model = model_builder.build_model(model_config_file, dataset, device)
model.load_state_dict(state_dict)

#model = torch.load('{}/model.pt'.format(model_path))
model.eval()

ts = torch.arange(T)[None,...].long()
noises = torch.randn(length, 26, last_frame.shape[-1]).float()
last_frame = torch.tensor(dataset.motion_flattened[idx][None,...]).float()
print(last_frame.device, last_frame.shape,model.device)
print(last_frame)
for i in range(length):
    noise = noises[i][None,...]
    last_frame = model(last_frame, noise, ts)
    gen_seq[i] = last_frame

gen_seq = gen_seq.cpu().numpy()
gen_seq = dataset.denorm_data(gen_seq)

jnts_lst = []
for mode in dataset.data_component:
    jnts = dataset.x_to_jnts(gen_seq, mode)
    jnts_lst.append(jnts)
    
jnts_lst = np.array(jnts_lst)
print(f'torch: "{gen_seq.shape}"')
dataset.plot_jnts(jnts_lst,path='torch_ckpt_gen')



###########
gen_seq = np.zeros((length, last_frame.shape[-1]))
ts = np.arange(T)[None,...]
last_frame = dataset.motion_flattened[idx][None,...].astype(np.float32)
# Print Result
noises = noises.numpy()
print(last_frame)
for i in range(length):
    noise = noises[i][None,...]
    last_frame = ort_sess.run(None, {'y0': last_frame, 'l_input_noises_':noise, 'l_input_ts_':ts})[0]
    gen_seq[i] = last_frame
    
gen_seq = dataset.denorm_data(gen_seq)
print(f'onnx: "{gen_seq.shape}"')

jnts_lst = []
for mode in dataset.data_component:
    jnts = dataset.x_to_jnts(gen_seq, mode)
    jnts_lst.append(jnts)
jnts_lst = np.array(jnts_lst)
dataset.plot_jnts(jnts_lst,path='onnx_gen')