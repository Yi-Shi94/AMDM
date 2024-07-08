import yaml
import model.amdm_model as amdm_model

def build_model(model_config_file, dataset, device):
    model_config = load_model_file(model_config_file)
    model_name = model_config["model_name"]
    print("Building {} model".format(model_name))

    if (model_name == amdm_model.AMDM.NAME):
        model = amdm_model.AMDM(config=model_config, dataset=dataset,device=device)
   
    else:
        assert(False), "Unsupported model: {}".format(model_name)
        
    return model

def load_model_file(file):
    with open(file, "r") as stream:
        config = yaml.safe_load(stream)
    return config
