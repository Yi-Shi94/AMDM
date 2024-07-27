import torch
import torch.onnx
import model.model_builder as model_builder
import dataset.dataset_builder as dataset_builder

device = 'cpu'

model_path = 'output/base/amdm_lafan1'
model_config_file = 'coutput/base/config.yaml'

dataset = dataset_builder.build_dataset(model_config_file)
#model = torch.load('{}/model.pt'.format(model_path))
#torch.save(model.state_dict(), '{}/model_weights_new_test.pth'.format(model_path))

sa_model = model_builder.build_model(model_config_file, dataset, device)
sa_model.load_state_dict(torch.load('{}/model_param.pth'.format(model_path)))

#model.eval()
dummy_x = (torch.randn(1, sa_model.frame_dim), torch.randn(1, sa_model.T+1, sa_model.frame_dim), torch.randint(0, sa_model.T, (1, sa_model.T)))


torch.onnx.dynamo_export(sa_model,*dummy_x).save("amdm.onnx")                       
                  