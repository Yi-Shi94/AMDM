
from dataset.util.humanml3d.util.get_opt import get_opt
from dataset.util.humanml3d.motion_loader.eval_humanml3d_amdm_dataset import eval_HumanML3D_AMDM
from dataset.util.humanml3d.util.word_vectorizer import WordVectorizer

from torch.utils.data import DataLoader, Dataset
import numpy as np
from torch.utils.data._utils.collate import default_collate


def collate_fn(batch):
    #batch.sort(key=lambda x: x[3], reverse=True)
    return default_collate(batch)


class MMGeneratedDataset(Dataset):
    def __init__(self, opt, motion_dataset, w_vectorizer):
        self.opt = opt
        self.dataset = motion_dataset.mm_generated_motion
        self.w_vectorizer = w_vectorizer

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, item):
        data = self.dataset[item]
        mm_motions = data['mm_motions']
        m_lens = []
        motions = []
        for mm_motion in mm_motions:
            m_lens.append(mm_motion['length'])
            motion = mm_motion['motion']
            # We don't need the following logic because our sample func generates the full tensor anyway:
            # if len(motion) < self.opt.max_motion_length:
            #     motion = np.concatenate([motion,
            #                              np.zeros((self.opt.max_motion_length - len(motion), motion.shape[1]))
            #                              ], axis=0)
            motion = motion[None, :]
            motions.append(motion)
        m_lens = np.array(m_lens, dtype=np.int)
        motions = np.concatenate(motions, axis=0)
        sort_indx = np.argsort(m_lens)[::-1].copy()
        # print(m_lens)
        # print(sort_indx)
        # print(m_lens[sort_indx])
        m_lens = m_lens[sort_indx]
        motions = motions[sort_indx]
        return motions, m_lens




# our loader
def get_mdm_loader(model, eval_dataset, batch_size, dataloader, mm_num_samples, mm_num_repeats, max_motion_length, num_samples_limit, save_dir=None, seed=0):
    opt = {
        'name': 'test',  # FIXME
    }
    print('Generating %s ...' % opt['name'])
    # dataset = CompMDMGeneratedDataset(opt, ground_truth_dataset, ground_truth_dataset.w_vectorizer, mm_num_samples, mm_num_repeats)
    dataset = eval_HumanML3D_AMDM(model, eval_dataset, dataloader, mm_num_samples, mm_num_repeats, max_motion_length, num_samples_limit, save_dir=save_dir, seed=seed)

    #mm_dataset = MMGeneratedDataset(opt, dataset, dataloader.dataset.w_vectorizer)

    # NOTE: bs must not be changed! this will cause a bug in R precision calc!
    motion_loader = DataLoader(dataset, batch_size=batch_size, collate_fn=collate_fn, drop_last=True, num_workers=4)
    #mm_motion_loader = DataLoader(mm_dataset, batch_size=1, num_workers=1)

    print('Generated Dataset Loading Completed!!!')

    return motion_loader, None