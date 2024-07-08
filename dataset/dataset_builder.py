import dataset.amass_dataset as amass_dataset
import dataset.mdm_dataset as mdm_dataset
import dataset.humanml3d_dataset as humanml3d_dataset
import dataset.lafan1_dataset as lafan1_dataset
import dataset.lafan1_hetero_dataset as lafan1_hetero_dataset
import dataset.style100_dataset as style100_dataset
import yaml

def build_dataset(config_file, device):
    config = load_config_file(config_file)
    if "data" not in config:
        dataset_name = config['dataset_name']
        dataset_class_name = config.get('dataset_class_name', dataset_name)
    else:
        dataset_name = config["data"]["dataset_name"]
        dataset_class_name = config["data"].get('dataset_class_name', dataset_name)
    print("Loading {} dataset class".format(dataset_class_name))
    print("Loading {} dataset".format(dataset_name))

    if (dataset_class_name == amass_dataset.AMASS.NAME):
        dataset = amass_dataset.AMASS(config)
    elif (dataset_class_name == humanml3d_dataset.HumanML3D.NAME):
        dataset = humanml3d_dataset.HumanML3D(config)
    elif (dataset_class_name == mdm_dataset.HumanML3D.NAME):
        dataset = mdm_dataset.HumanML3D(config)
    elif (dataset_class_name == lafan1_dataset.LAFAN1.NAME):
        dataset = lafan1_dataset.LAFAN1(config)
    elif (dataset_class_name == lafan1_hetero_dataset.LAFAN1_hetero.NAME):
        dataset = lafan1_hetero_dataset.LAFAN1_hetero(config)
    elif (dataset_class_name == style100_dataset.STYLE100.NAME):
        dataset = style100_dataset.STYLE100(config)
    else:
        assert(False), "Unsupported dataset class: {}".format(dataset_class_name)
    return dataset

def load_config_file(file):
    with open(file, "r") as stream:
        config = yaml.safe_load(stream)
    return config