import numpy as np
import torch
import copy 
import os

FOOT2CM = 100*0.3048
FOOT2METER = 0.3048
METER2FOOT = 1/0.3048

def num_valid_frames(motion_clips):
    if len(motion_clips.shape)>2:
        num_clips = motion_clips.shape[0]
    else:
        num_clips = 1
    return np.count_nonzero(np.isnan(motion_clips))/num_clips

def compute_penetrate_humor(toe_idx, motion_clips):
    # unit m, 
    # motions_clips: BXNxJx3
    thres = [0.00, 0.03, 0.06, 0.09, 0.12, 0.15] 
    percetage = [0, 0, 0, 0, 0, 0 ]
    toe_coords = motion_clips[..., toe_idx, :] #B x N x 2 x 3
    toe_coords_z = toe_coords[...,1].reshape(-1, 2) #B x N x 2
    toe_val_pen_z = toe_coords_z.min(axis=-1) #B*N

    for i,t in enumerate(thres):
        flag = -toe_coords_z > t
        flag = flag[...,0] * flag[...,1] #B x N
        percetage[i] = np.sum(flag)/toe_coords_z.shape[0]
    
    return np.mean(percetage), np.mean(toe_val_pen_z)

def compute_distmat(motion_clips):
    #In: BxNxJx3
    #Out:   BXN | BXB
    B = motion_clips.shape[0]
    N = motion_clips.shape[1]
    J = motion_clips.shape[2]
    ma = motion_clips[None,...] 
    mb = motion_clips[:,None,...]
    #diff_clips = np.power(ma - mb,2)
    diff_clips_flat = ma-mb
    #print(np.sum(motion_clips > 100))
    
    diff_clips = np.mean(np.linalg.norm(np.reshape(diff_clips_flat,(B,B,N,-1,3)),axis=-1),axis=-1)
    
    dist_mat = np.mean(diff_clips,axis=-1)
    return dist_mat

def extract_sk_lengths(joint_idxs, positions):
    #position: NxJx3
    # 
    #single frame rigid body restriction
    positions = positions.reshape(-1, *positions.shape[-2:])
    lengths = np.zeros((len(joint_idxs),positions.shape[0]))
    for i,(st,ed) in enumerate(joint_idxs):
        # positions[:,st] Nx3; positions[:,ed] Nx3
        length =  np.linalg.norm(positions[:,st] - positions[:,ed], axis=-1)
        lengths[i] = length
    return np.array(lengths)

def compute_ground_pen(foot_idx, positions, thres):
    #lengths = np.zeros((len(self.joint_idxs),positions.shape[0]))
    contact_idx = foot_idx
    contact_zs = positions[:,contact_idx,1]
    contact_zs_mean = contact_zs[contact_zs < thres].mean()
    contact_event = np.sum(contact_zs < 0)/(positions.shape[0])
    return contact_zs_mean, contact_event

def compute_apd(output_seqs):
    #B x N x F
    B = output_seqs.shape[0]
    dist_mat = compute_distmat(output_seqs)
    dist_mat = dist_mat[np.triu_indices(B, k = 1)]
    dist_mean = np.mean(dist_mat)    
    return dist_mean  #, dist_mean_flat * FOOT2CM


def compute_ade(output_seqs, ref_clip):
    ref_clip = ref_clip.squeeze()
    dist_lst = np.zeros((output_seqs.shape[0]))
    dist_joint_frame_lst = np.zeros((output_seqs.shape[0],output_seqs.shape[1]))

    for i,seq in enumerate(output_seqs):
        dist_joint_frame = np.linalg.norm(seq-ref_clip,axis=-1)
        dist_joint_frame = np.mean(dist_joint_frame,axis=-1)
        dist_mean = np.mean(dist_joint_frame,axis=-1)
        dist_lst[i] = dist_mean
        dist_joint_frame_lst[i] = dist_joint_frame
    
    min_idx =  np.argmin(dist_lst)
    dist_min = dist_lst[min_idx]
    dist_min_last  = dist_joint_frame_lst[min_idx,-1]
    return dist_min, dist_min_last


def compute_rigid_diff(links, output_seqs, ref_lengths):
    output_lengths = extract_sk_lengths(links, output_seqs)
    link_dist = np.abs(output_lengths - ref_lengths[...,None])
    return link_dist


def compute_foot_slide(foot_idx, output_seqs):
    contact_threshold = 0.3 #* 1 / 0.3048 
    output_seqs = output_seqs[..., foot_idx,:]
    
    out_foot_d = output_seqs[...,1:,:,:] - output_seqs[...,:-1,:,:]
    out_foot_dxdy = np.linalg.norm(out_foot_d[...,[0,2]],axis=-1) #global
    out_foot_z = output_seqs[..., 1:,:,1]
    out_foot_z = out_foot_z.reshape((*out_foot_z.shape[:-1],2,2))

    foot_slide_lst = np.zeros((*out_foot_z.shape[:-2],2))
    for i in range(out_foot_z.shape[-3]):
        foot_slide = out_foot_dxdy[..., i,[1,3]] * (
            2 - 2 ** np.clip((np.max(out_foot_z[...,i,:,:],axis=-1) / contact_threshold), 0, 1)
        ) 
        foot_slide_lst[:,i] = foot_slide

    return np.mean(foot_slide_lst)


def compute_jittering(output_seqs):
    a_seqs = np.diff(output_seqs, n=2, axis=-1)
    a_norm = np.linalg.norm(a_seqs,axis=-1)
    return a_norm


def compute_long_test_metrics(links, foot_idx, output_jnts, ref_jnts):
    ref_lengths = extract_sk_lengths(links, ref_jnts).mean(axis=-1)
    foot_slide = compute_foot_slide(foot_idx, output_jnts)
    jittering = compute_jittering(output_jnts)
    rigid = compute_rigid_diff(links, output_jnts, ref_lengths)
    stats = {
        'sliding':foot_slide,
        'jittering': jittering,
        'rigid':rigid
    }
    return stats


def compute_local_test_metrics(links, output_jnts, ref_jnts):        
    ref_lengths = extract_sk_lengths(links, ref_jnts).mean(axis=-1)
    jittering_gt = compute_jittering(ref_jnts)
    apd = compute_apd(output_jnts)
    ade, fde = compute_ade(output_jnts, ref_jnts)
    jittering = compute_jittering(output_jnts)
    rigid = compute_rigid_diff(links, output_jnts, ref_lengths)
    stats = {
        'local_apd':apd,
        'local_ade':ade,
        'local_fde':fde,
        'local_jittering': jittering,
        'local_rigid':rigid,
        'local_jittering_gt':jittering_gt
    }
    return stats


def compute_test_metrics(links, foot_idx, output_jnts, ref_jnts):        
    ref_lengths = extract_sk_lengths(links, ref_jnts).mean(axis=-1)
    slide_gt = compute_foot_slide(foot_idx, ref_jnts)
    jittering_gt = compute_jittering(ref_jnts)
    apd = compute_apd(output_jnts)
    ade, fde = compute_ade(output_jnts, ref_jnts)
    foot_slide = compute_foot_slide(foot_idx, output_jnts)
    jittering = compute_jittering(output_jnts)
    rigid = compute_rigid_diff(links, output_jnts, ref_lengths)

    stats = {
        'apd':apd,
        'ade':ade,
        'fde':fde,
        'sliding':foot_slide,
        'jittering': jittering,
        'rigid':rigid,
        'sliding_gt':slide_gt,
        'jittering_gt':jittering_gt
    }
    return stats

if __name__ == '__main__':
    pass
    

