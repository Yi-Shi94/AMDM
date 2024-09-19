import yaml

import model.amdm_model as amdm_model
import model.amdm_trainer as amdm_trainer
import model.amdm_text_model as amdm_text_model
import model.amdm_text_trainer as amdm_text_trainer

import dataset.dataset_builder as dataset_builder

def build_trainer(config_file, device):
    model_config = load_config_file(config_file)
    model_name = model_config["model_name"]
    #print(model_config)
    dataset = dataset_builder.build_dataset(config_file, load_full_dataset=True)

    print("Building {} trainer".format(model_name))
    if (model_name == amdm_model.AMDM.NAME):
        trainer = amdm_trainer.AMDMTrainer(config=model_config, dataset=dataset, device=device)
    if (model_name == amdm_text_model.AMDM.NAME):
        trainer = amdm_text_trainer.AMDMTrainer(config=model_config, dataset=dataset, device=device)

    else:
        assert(False), "Unsupported trainer: {}".format(model_name)
    return trainer

def load_config_file(file):
    with open(file, "r") as stream:
        config = yaml.safe_load(stream)
    return config

def get_feature_dim_dict(dataset):
    return {"frame_dim": dataset.frame_dim}