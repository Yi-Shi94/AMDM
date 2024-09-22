import torch
import numpy as np
from tqdm import tqdm
import os
import os.path as osp
import codecs as cs
import dataset.util.plot as plot_util
from dataset.util.humanml3d.util.paramUtil import *
import dataset.humanml3d_dataset as humanml3d_dataset
import json
from numpy import dot
from numpy.linalg import norm

class HumanML3D(humanml3d_dataset.HumanML3D):
    NAME = 'HumanML3D_TEXT'
    def __init__(self, config):
        self.labels = []
        super().__init__(config)
        self.text_path = config['data']['text_path']
        self.text_model_path = config['data']['text_model_path']
        self.sentence_transformer = self.init_text_model(self.text_model_path)
        #test_txt = ['hello!', 'bye', 'hi']
        #test_emb = self.sentence_transformer.encode(test_txt)
       
        #cos_sim1 = dot(test_emb[0], test_emb[1])/(norm(test_emb[0])*norm(test_emb[1]))
        #cos_sim2 = dot(test_emb[0], test_emb[2])/(norm(test_emb[0])*norm(test_emb[2]))
        #print(cos_sim1, cos_sim2)
        
        self.train_embs = self.load_sentence_embedding_from_split(self.train_split_file)
        #self.val_embs = self.load_sentence_embedding_from_split(self.val_split_file)
        #self.test_embs = self.load_sentence_embedding_from_split(self.test_split_file)

    def init_text_model(self, path):
        #import transformers
        from sentence_transformers import SentenceTransformer
        #from transformers import AutoTokenizer, AutoModel
        if os.path.exists(path):
            print('Logging local model: {}'.format(path))
        else:
            print('Path not found, downloading ckpt...')
        model = SentenceTransformer(path)
        return model

    def encode_text(self, text):
        return self.sentence_transformer.encode(text)


    def load_sentence_embedding_from_split(self, split_file, reprocess=False):
        base_name = os.path.basename(split_file)[:-4]
        base_dir = os.path.dirname(split_file)
        out_emb_file = os.path.join(base_dir, base_name+'_emb.pt')
        out_dict_file = os.path.join(base_dir, base_name+'_dict')

        if reprocess or not os.path.exists(out_emb_file):
            text_dicts = {}
            text_idx_name_lst = []
            texts = []
            
            with open(split_file) as f:
                lines = [osp.join(self.text_path,x.strip()+'.txt') for x in f.readlines()]
            text_idx = 0
            
            for i, line in enumerate(tqdm(lines)):
                data_lst = self.process_text(line)
                for cur_dict in data_lst:
                    text_name_lst.append(data_lst['motion_name'])
                    text_dicts[data_lst['motion_name']] = []
                    cur_dict['text_idx'] = text_idx
                    text_dicts[data_lst['motion_name']].append(cur_dict)
                    texts.append(cur_dict['caption'])
                    text_idx += 1

            embs = self.encode_text(texts)
            torch.save(embs, out_emb_file)
            with open(out_dict_file, 'w') as fout:
                json.dump(text_dicts, fout)

        else:
            embs = torch.load(out_emb_file)
            text_dicts = json.load(out_emb_file)
        return embs, text_dicts

    
    def load_new_dataset(self, split):
        new_data = []
        with open(split) as f:
            lines = [osp.join(self.path,x.strip()+'.npy') for x in f.readlines()]
        
        for i, line in enumerate(tqdm(lines)):
            data = self.process_data(line)
            #data = self.load_new_data(line)
            #data = self.transform_new_data(data)
            new_data.append(data)

        #new_data_flattened = np.array(new_data_flattened)
        return new_data


    def process_text(self,fname):
        text_data = []
        with cs.open(fname) as f:
            file_base_name = os.path.basename(fname)
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
                text_dict['motion_name'] = file_base_name
                text_dict['motion_idx'] = i
                text_dict['tokens'] = tokens
                text_dict['st_frame'] = int(f_tag) * 20
                text_dict['end_frame'] = int(to_tag) * 20
                text_data.append(text_dict)
        return text_data
        

