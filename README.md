# <p align="center"> Interactive Character Control with Auto-Regressive Motion Diffusion Models </p>
## <p align="center"> [Yi Shi](https://github.com/Yi-Shi94/), [Jingbo Wang](https://wangjingbo1219.github.io/), [Xuekun Jiang](), [Bingkun Lin](), [Bo Dai](https://daibo.info/), [Xue Bin Peng](https://xbpeng.github.io/) </p>
<p align="center">
  <img width="100%" src="assets/images/AMDM_teaser.png"/>
</p>

## Implementation of Auto-regressive Motion Diffusion Model (A-MDM)
We implement a pytorch framework for kinematic based auto-regressive models. To use our framework, follow the instruction below:

## Usage
### Base Model

#### Training
LaFAN1:
```
python run_base.py --arg_file args/amdm_lafan1_train.txt
```
100STYLE:
```
python run_base.py --arg_file args/amdm_style100_train.txt
```

#### Inference
LaFAN1:
```
python run_env.py --arg_file args/RP_amdm_lafan1.txt
```
100STYLE:
```
python run_env.py --arg_file args/RP_amdm_style100.txt
```

### High-Level Controller

#### Training

#### Inference

### Inpainting

### Checkpoint Download




## Acknowledgement
The RL modules are built using existing code base of [MotionVAE](https://github.com/electronicarts/character-motion-vaes)


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
