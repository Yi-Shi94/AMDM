import torch
import numpy as np
from tqdm import tqdm
import os
import os.path as osp
import codecs as cs
import dataset.util.plot as plot_util
from dataset.util.humanml3d.util.paramUtil import *
import dataset.humanml3d_dataset as humanml3d_dataset

class HumanML3D(humanml3d_dataset.HumanML3D):
    NAME = 'HumanML3D_TEXT'
    def __init__(self, config):
        self.text_path = config['data']['text_path']
        self.text_emb_model_path = config['model']['model_path']
        self.text_emb_model = self.init_emb_model(self.text_emb_model_path)
        super().__init__(config)

    def init_emb_model(self, path):
        pass

    def load_text_from_split(self, split_file):
        texts = []
        with open(split_file) as f:
            lines = [osp.join(self.text_path,x.strip()+'.txt') for x in f.readlines()]
        for i, line in enumerate(tqdm(lines)):
            texts.append(self.process_text(line))
        embs = self.encode_text(texts)
        return embs

    def encode_text(self, texts, batch_size = 16):
        num_batch = len(texts) // batch_size 
        embs = []
        for i in range(num_batch):
            embs.append(self.text_emb_model(texts[i*batch_size:(i+1)*batch_size]))
        embs = torch.stack(embs).tolist()
        return embs

    def process_text(self,path):
        text_data = []
        with cs.open(path) as f:
            file_base_name = os.path.basename(path)
            for i, line in enumerate(f.readlines()):
                text_dict = {}
                line_split = line.strip().split('#')
                caption = line_split[0]
                tokens = line_split[1].split(' ')
                f_tag = float(line_split[2])
                to_tag = float(line_split[3])
                f_tag = 0.0 if np.isnan(f_tag) else f_tag
                to_tag = 0.0 if np.isnan(to_tag) else to_tag

                text_dict['caption'] = caption
                text_dict['motion_name'] = '{}_{}'.format(file_base_name, i)
                text_dict['tokens'] = tokens
                text_dict['st_frame'] = int(f_tag)*30
                text_dict['end_frame'] = int(to_tag)*30
                text_data.append(text_dict)
        return text_data
        

