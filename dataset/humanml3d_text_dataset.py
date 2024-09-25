import random
import numpy as np
from tqdm import tqdm
import os
import os.path as osp
import codecs as cs
import dataset.util.plot as plot_util
from dataset.util.humanml3d.util.paramUtil import *
import dataset.humanml3d_dataset as humanml3d_dataset
from numpy import dot
from numpy.linalg import norm

class HumanML3D(humanml3d_dataset.HumanML3D):
    NAME = 'HumanML3D_TEXT'
    def __init__(self, config):
        
        self.text_path = config['data']['text_path']
        self.text_model_path = config['data']['text_model_path']
        self.lm_framework = config['data']['lm_framework']
        self.model, self.tokenizer = self.init_text_model(self.text_model_path)
        self.text_emb_dim = self.get_text_emb_dim()

        super().__init__(config)
        out_emb_file = os.path.join(self.text_path, 'text_embs.npz')
        
        if os.path.exists(out_emb_file):
            with np.load(out_emb_file, allow_pickle=True) as emb_f:
                self.text_embs = emb_f['text_embs']
                self.frame_text_idx = emb_f['frame_text_idx']

        else:
            self.text_num = 0
            self.text_embs = []
            #self.text_motion_idx = [] #N_len_text; which motion does each text belongs to
            self.frame_text_idx = [] #N_len_frame; which text does a motion frame associated with
            #self.motion_text_ids = [] #N_len_motion; nested idx for text, idx of texts descr for each motion
            #self.text_motion_span = []  #N_len_motion; nested idx for text, span of motion which corresponds to each text
            motion_paths = self.get_motion_fpaths()
            for motion_path in tqdm(motion_paths):
                base_file = os.path.basename(motion_path)
                text_path = os.path.join(self.text_path, base_file[:-4]+'.txt')
                cur_frame_text_idx, cur_text_embs = self.process_text(motion_path, text_path)
                self.text_embs.extend(cur_text_embs)
                self.frame_text_idx.extend(cur_frame_text_idx)
            self.text_embs = np.concatenate(self.text_embs, axis=0)

            np.savez(out_emb_file, text_embs=self.text_embs, frame_text_idx=self.frame_text_idx)
       
        #cos_sim1 = dot(test_emb[0], test_emb[1])/(norm(test_emb[0])*norm(test_emb[1]))
        #cos_sim2 = dot(test_emb[0], test_emb[2])/(norm(test_emb[0])*norm(test_emb[2]))
        #print(cos_sim1, cos_sim2)
    
    def embop_cosine_dist(self, a, b):
        b = b.T
        dist = np.dot(a, b)/ \
            (np.linalg.norm(a)*np.linalg.norm(b))
        return dist


    def get_text_emb_dim(self):
        texts = ['a man walks up and down from either stairs, rocks, or some unlevel terrain requiring a step.','climb up steps with both legs', 'a man flaps his arms like a chicken while bending up and down.']
        embs = [self.encode_text(x) for x in texts]
        dist_01 = self.embop_cosine_dist(embs[0], embs[1])
        dist_02 = self.embop_cosine_dist(embs[0], embs[2])
        dist_12 = self.embop_cosine_dist(embs[1], embs[2])
        print(dist_01, dist_02, dist_12)
        return embs[0].shape[-1]


    def init_text_model(self, path):
        if os.path.exists(path):
            print('Logging local model: {}'.format(path))
        else:
            print('Path not found, downloading ckpt...')

        if self.lm_framework == 'transformers_encdec':
            from transformers import AutoTokenizer, T5EncoderModel
            tokenizer = AutoTokenizer.from_pretrained(path)
            model = T5EncoderModel.from_pretrained(path)

        elif self.lm_framework == 'sentence_tranformers':
            from sentence_transformers import SentenceTransformer
            tokenizer = None
            model = SentenceTransformer(path)
        
        elif self.lm_framework == 'clip':
            pass
        #else:
        #    pass
        return model, tokenizer

    def encode_text(self, text, maxlen=512):
        if self.lm_framework == 'transformers_encdec':
            input_ids = self.tokenizer(
            text, 
            max_length=maxlen,
            return_tensors="pt",
            padding=True).input_ids  

            output = self.model(input_ids=input_ids).last_hidden_state.detach().numpy()
            output = np.mean(output, axis=1)

        elif self.lm_framework == 'sentence_tranformers':
            output = self.model.encode(text)

        elif self.lm_framework == 'clip':
            pass

        return output



    def extract_text(self,fname):
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
                text_dict['text_idx'] = i
                text_dict['tokens'] = tokens
                text_dict['st_frame'] = int(f_tag) * 20
                text_dict['end_frame'] = int(to_tag) * 20
                text_data.append(text_dict)
        return text_data


    def process_text(self, motion_fname, text_fname):
        final_x = np.load(motion_fname)
        
        
        if np.any(np.isnan(final_x)):
            return
        
        text_data = self.extract_text(text_fname)
        motion_length = final_x.shape[0]
        
        cur_texts = []
        cur_frame_text_bool = [np.array([0 for _ in range(motion_length)]) for _ in range(len(text_data))]
        cur_frame_text_idx = []
        
        cumul_text_num = len(self.text_embs)
        for i, cur_dict in enumerate(text_data):
            cur_texts.append(cur_dict['caption'])
            st_frame = int(cur_dict['st_frame'])
            ed_frame = int(cur_dict['end_frame']) if cur_dict['end_frame']>0.0 else motion_length+1  
            cur_frame_text_bool[i][st_frame:ed_frame] = 1 
            cur_frame_text_bool[i] = list(cur_frame_text_bool[i]) 
        
        for i in range(len(cur_frame_text_bool[0])):
            true_indices = []
            for j, lst in enumerate(cur_frame_text_bool):
                if lst[i]:
                    true_indices.append(cumul_text_num+j)
            cur_frame_text_idx.append(true_indices)
        
        #self.plot_jnts(self.x_to_jnts(final_x))

        cur_text_embs = self.encode_text(cur_texts)
        self.text_num += len(text_data)     
        self.num_file += 1

        return cur_frame_text_idx, cur_text_embs

    
    def __getitem__(self, idx):
        idx = self.valid_idx[idx]
        motion = self.motion_flattened[idx: idx+self.rollout]
        text_embs = np.zeros((motion.shape[0], self.text_emb_dim))

        text_idxs = self.frame_text_idx[idx: idx+self.rollout]
        for i, text_idx in enumerate(text_idxs):
            if len(text_idx) == 0:
                continue
            else:
                text_embs[i,:] = self.text_embs[random.choice(text_idx)]
        
        
        return  motion, text_embs






    """ 
    def load_sentence_embedding_from_split(self, split_file, reprocess=False):
        base_name = os.path.basename(split_file)[:-4]
        base_dir = os.path.dirname(split_file)
        out_emb_file = os.path.join(base_dir, base_name+'_emb.pt')
        out_dict_file = os.path.join(base_dir, base_name+'_textmap')

        if reprocess or not os.path.exists(out_emb_file):
            motion_lst = []
            text_motion_idx_lst = {}
            motion_text_idxs_map = {}
            texts = []
            
            with open(split_file) as f:
                lines = [osp.join(self.text_path,x.strip()+'.txt') for x in f.readlines()]
            text_idx = 0
            
            for _, line in enumerate(tqdm(lines)):
                motion_lst.append(line.strip())

            for motion_name in motion_lst:
                data_lst = self.process_text(motion_name)
                for cur_dict in data_lst:
                    cur_dict['text_idx'] = text_idx
                    map_name2idx[data_lst['motion_name']].append(text_idx)
                    texts.append(cur_dict['caption'])
                    text_idx += 1

            text_embs = self.encode_text(texts)
            torch.save(text_embs, out_emb_file)
            with open(out_dict_file, 'w') as fout:
                json.dump(map_name2idx, fout)

        else:
            embs = torch.load(out_emb_file)
            map_name2idx = json.load(out_emb_file)
        return embs, map_name2idx 
    """

