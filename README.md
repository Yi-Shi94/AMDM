# <p align="center"> Interactive Character Control with Auto-Regressive Motion Diffusion Models </p>
### <p align="center"> [Yi Shi](https://github.com/Yi-Shi94/), [Jingbo Wang](https://wangjingbo1219.github.io/), [Xuekun Jiang](), [Bingkun Lin](), [Bo Dai](https://daibo.info/), [Xue Bin Peng](https://xbpeng.github.io/) </p>
<p align="center">
  <img width="100%" src="assets/images/AMDM_teaser.png"/>
</p>

## Links
[paper](https://arxiv.org/html/2306.00416v2) | [demo]() | [video](https://www.youtube.com/watch?v=5WE9hy0xCI4&ab_channel=YISHI) | [poster]()

## Implementation of Auto-regressive Motion Diffusion Model (A-MDM)
We have implemented a PyTorch framework for kinematic-based auto-regressive models, supporting both training and inference for A-MDM. Our framework also includes features for real-time inpainting and reinforcement learning-based interactive control tasks. If you have any questions regarding A-MDM, please feel free to leave a message.

## Dataset Preparation
### LaFAN1:
[Download](https://github.com/ubisoft/ubisoft-laforge-animation-dataset) and extract under ```./data/``` directory.
We didn't include files with a prefix of 'obstacle'

### 100STYLE:
[Download](https://www.ianxmason.com/100style/) and extract under ```./data/``` directory.

### Any other BVH dataset:
Download and extract under ```./data/``` directory. Create a yaml config file in ```./config/model/```, 

### AMASS:
Follow the procedure described in the repo of [HuMoR](https://github.com/davrempe/humor) 

### HumanML3D:
Follow the procedure described in the repo of [HumanML3D](https://github.com/EricGuo5513/HumanML3D.git) 


### Sanity Check:
Specify your model config file in 
```
python run_sanity_data.py
```

## Base Model
### Training

```
python run_base.py --arg_file args/amdm_DATASET_train.txt
```
or
```
python run_base.py
--model_config config/model/amdm_lafan1.yaml
--log_file output/base/amdm_lafan1/log.txt

--int_output_dir output/base/amdm_lafan1/
--out_model_file output/base/amdm_lafan1/model_param.pth

--mode train
--master_port 0
--rand_seed 122
```
Temporary Visualization is saved in --int_output_dir


### Inference
```
python run_env.py --arg_file args/RP_amdm_DATASET.txt
```

#### Inpainting
```
python run_env.py --arg_file args/PI_amdm_DATASET.txt
```

### High-Level Controller


#### Training
```
python run_env.py --arg_file args/ENV_train_amdm_DATASET.txt
```
#### Inference
```
python run_env.py --arg_file args/ENV_test_amdm_DATASET.txt
```

### Installation
```
conda create -n amdm python=3.7
pip install -r requirement.txt
```

### Update
1. July 28 2024, repo released
2. upcoming, weight upload for 100STYLE & HumanML3D


## Acknowledgement
The RL related modules are built using existing code base of [MotionVAE](https://github.com/electronicarts/character-motion-vaes)

## BibTex
```
@article{
        shi2024amdm,
        author = {Shi, Yi and Wang, Jingbo and Jiang, Xuekun and Lin, Bingkun and Dai, Bo and Peng, Xue Bin},
        title = {Interactive Character Control with Auto-Regressive Motion Diffusion Models},
        year = {2024},
        issue_date = {August 2024},
        publisher = {Association for Computing Machinery},
        address = {New York, NY, USA},
        volume = {43},
        journal = {ACM Trans. Graph.},
        month = {jul},
        keywords = {motion synthesis, diffusion model, reinforcement learning}
      }
```
