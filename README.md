# <p align="center"> Interactive Character Control with Auto-Regressive Motion Diffusion Models </p>
### <p align="center"> [Yi Shi](https://github.com/Yi-Shi94/), [Jingbo Wang](https://wangjingbo1219.github.io/), [Xuekun Jiang](), [Bingkun Lin](), [Bo Dai](https://daibo.info/), [Xue Bin Peng](https://xbpeng.github.io/) </p>
<p align="center">
  <img width="100%" src="assets/images/AMDM_teaser.png"/>
</p>

## Links
[page](https://yi-shi94.github.io/amdm_page/) | [paper](https://arxiv.org/pdf/2306.00416v4) | [video](https://www.youtube.com/watch?v=5WE9hy0xCI4&ab_channel=YISHI) | [poster](https://docs.google.com/presentation/d/1KRxJh2ZoyV7dtKd25s_R4KGqslxCJyeqm5OGw24TKZU/edit?usp=sharing) | [slides](https://docs.google.com/presentation/d/1kA_LT9zi4nb7FbJjZGD_g692NfGSKbfXBuVEQxUEXAg/edit?usp=sharing)

## Implementation of Auto-regressive Motion Diffusion Model (A-MDM)
We developed a PyTorch framework for kinematic-based auto-regressive motion generation models, supporting both training and inference. Our framework also includes implementations for real-time inpainting and reinforcement learning-based interactive control. If you have any questions about A-MDM, please feel free to reach out via ISSUE or email.


## Update
1. July 28 2024, framework released.
2. Aug 24 2024, LAFAN1 15step checkpoint released. 
3. Sep 5 2024, 100STYLE 25step checkpoint released. 
4. Stay tuned for support for more dataset.


## Checkpoints
Download, unzip and merge with your output directory.

[LAFAN1_15step](https://drive.google.com/file/d/1a3emD8C5hN4wbTuPYhI0WytSMCuGoLNs/view?usp=sharing)
[100STYLE_25step](https://drive.google.com/file/d/1-ju_XW9JsHrBuLORl8-n7jJiry5C_3Fn/view?usp=sharing)

## Dataset Preparation
### LaFAN1:
[Download](https://github.com/ubisoft/ubisoft-laforge-animation-dataset) and extract under ```./data/``` directory.
BEWARE: We didn't include files with a prefix of 'obstacle' in our experiments. 

### 100STYLE:
[Download](https://www.ianxmason.com/100style/) and extract under ```./data/``` directory.

### Arbitrary BVH dataset:
Download and extract under ```./data/``` directory. Create a yaml config file in ```./config/model/```, 

### AMASS:
Follow the procedure described in the repo of [HuMoR](https://github.com/davrempe/humor)

### HumanML3D:
Follow the procedure described in the repo of [HumanML3D](https://github.com/EricGuo5513/HumanML3D.git) 

### Sanity Check:
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
Training time visualization is saved in --int_output_dir


### Inference
```
python run_env.py --arg_file args/RP_amdm_DATASET.txt
```

### Inpainting
```
python run_env.py --arg_file args/PI_amdm_DATASET.txt
```

## High-Level Controller


### Training
```
python run_env.py --arg_file args/ENV_train_amdm_DATASET.txt
```
### Inference
```
python run_env.py --arg_file args/ENV_test_amdm_DATASET.txt
```

## Installation
```
conda create -n amdm python=3.7
conda activate amdm
pip install -r requirement.txt
mkdir output && mkdir data
```

## For users wish to create more variants given a mocap dataset
1. Train the base model
2. Follow the main function in gen_base_bvh.py, you can generate diverse motion given any starting pose:
[![](https://markdown-videos-api.jorgenkh.no/youtube/DniQWu_4Kag)](https://youtu.be/DniQWu_4Kag)


## Acknowledgement
Part of the RL modules utilized in our framework are based on the existing codebase of [MotionVAE](https://github.com/electronicarts/character-motion-vaes), please cite their work if you find using RL to guide autoregressive motion generative models helpful to your research.

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
