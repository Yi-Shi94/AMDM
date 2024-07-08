import torch
import torch.onnx
import model.model_builder as model_builder
import dataset.dataset_builder as dataset_builder

device = 'cpu'

model_path = 'output/base/amdm_lafan1_new_4_conti3_full'
model_config_file = 'config/model/amdm_lafan1_subj5.yaml'

dataset = dataset_builder.build_dataset(model_config_file, device=device)

model = torch.load('{}/model.pt'.format(model_path))
torch.save(model.state_dict(), '{}/model_weights_new_test.pth'.format(model_path))

sa_model = model_builder.build_model(model_config_file, dataset, device)
sa_model.load_state_dict(torch.load('{}/model_weights_new_test.pth'.format(model_path)))

model.eval()
dummy_x = (torch.randn(1, sa_model.frame_dim), torch.randn(1, sa_model.T+1, sa_model.frame_dim), torch.randint(0, sa_model.T, (1, sa_model.T)))


torch.onnx.dynamo_export(sa_model,*dummy_x).save("my_simple_model.onnx")                       
                  # model input (or a tuple for multiple inputs)   # where to save the model (can be a file or file-like object)
                  #export_params=True,        # store the trained parameter weights inside the model file
                  #opset_version=17,          # the ONNX version to export the model to
                  #do_constant_folding=True,  # whether to execute constant folding for optimization
                  #input_names = ['input_lastx','input_noises'],   # the model's input names
                  #output_names = ['output'], # the model's output names
                  #dynamic_axes={'input_lastx' : {0 : 'batch_size'},
                  #              'input_noises' : {0 : 'batch_size'},   # variable length axes
                  #              'output' : {0 : 'batch_size'}})