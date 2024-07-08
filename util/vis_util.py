import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.animation as animation
from mpl_toolkits.mplot3d import axes3d, Axes3D

import numpy as np
import copy 
import torch

def rot(yaw):
    cs = np.cos(yaw)
    sn = np.sin(yaw)
    return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])

def vis_skel(x, links, save_path=None):
    def rot(yaw):
        cs = np.cos(yaw)
        sn = np.sin(yaw)
        return np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])
    
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    if isinstance(x, torch.Tensor):
        x = x.cpu().detach().numpy()
    
    if x.shape[-1] <= 267 and x.shape[-1]>=69:
        dxdy = x[...,:2] 
        dr = x[...,2]
        x = np.reshape(x[...,3:69],(-1,22,3))
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],3))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)

        for i in range(1,x.shape[0]):
           cur_pos = np.zeros((1,3))
           cur_pos[0,0] = dxdy[i,0]
           cur_pos[0,2] = dxdy[i,1]
           dpm += np.dot(cur_pos,rot(yaws[i]))
           dpm_lst[i,:] = copy.deepcopy(dpm)
           x[i,:,:] = np.dot(x[i,:,:],rot(yaws[i])) + copy.deepcopy(dpm)

    elif x.shape[-1] == 66:
        x = np.reshape(x,(-1,22,3))

    if x.shape[0] == 1:
        x = x[0]
    
    if len(x.shape)==2:    
        ax.scatter(x[:,0],  x[:, 2], x[:, 1])
        for st,ed in links:
            pt_st = x[st]
            ed_st = x[ed]
            ax.plot([pt_st[0],ed_st[0]],[pt_st[2],ed_st[2]],[pt_st[1],ed_st[1]],color='r')

        ax.set_xlim(-100, 100)
        ax.set_ylim(-100, 100)
        ax.set_zlim(-100, 100)
        
    elif len(x.shape)==3:
    
        link_data = np.zeros((len(links),x.shape[0]-1,3,2))
        xini = x[0]
        link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,2],xini[ed,2]],[xini[st,1],xini[ed,1]],color='r')[0]
                        for st,ed in links]

        ax.set_xlabel('$X$')
        ax.set_ylabel('$Y$')
        ax.set_zlabel('$Z$')
        
        for i in range(1,x.shape[0]):
            for j,(st,ed) in enumerate(links):
                pt_st = x[i-1,st] #- y_rebase
                pt_ed = x[i-1,ed] #- y_rebase
                link_data[j,i-1,:,0] = pt_st
                link_data[j,i-1,:,1] = pt_ed
                
        def update_links(num, data_lst, obj_lst):
            cur_data_lst = data_lst[:,num,:,:] 
            cur_root = cur_data_lst[4,:,0]
            root_x = cur_root[0]
            root_z = cur_root[2]
            for obj, data in zip(obj_lst, cur_data_lst):
                obj.set_data(data[[0,2],:])
                obj.set_3d_properties(data[1,:])
    
                ax.set_xlim(root_x-1, root_x+1)
                ax.set_zlim(0, 2)
                ax.set_ylim(root_z-1, root_z+1)
        
        line_ani = animation.FuncAnimation(fig, update_links, x.shape[0]-1, fargs=(link_data, link_obj),
                                interval=50, blit=False)
        if save_path is not None:
            writergif = animation.PillowWriter(fps=30) 
            line_ani.save(save_path+'.gif', writer=writergif)

    if save_path is None:
        plt.show()
    plt.close()


def vis_traj(clips, save_path=None):
    cmap = cm.get_cmap('Spectral')
    map_idxs = list(np.arange(0,len(clips))/len(clips))
    fig = plt.figure()

    # Add a subplot to the figure
    ax = fig.add_subplot(1, 1, 1)
    for ic in range(len(clips)):
        # Plot the data
        ax.plot(clips[ic,:,0,0], clips[ic,:,0,2], 'b-', linewidth=2, c=cmap(map_idxs[ic]))
    if save_path:
        plt.savefig(save_path)
    else:
        plt.show()
    return 

def vis_traj_from_norm(clips, save_path=None):
    cmap = cm.get_cmap('Spectral')
    map_idxs = list(np.arange(0,len(clips))/len(clips))
    fig = plt.figure()

    # Add a subplot to the figure
    ax = fig.add_subplot(1, 1, 1)
    for ic in range(len(clips)):
        clip = clips[ic]
        dxdy = clip[...,:2] 
        dr = clip[...,2]
        #x = np.reshape(clips[...,3:3+3*self.num_joint],(-1,self.num_joint,3))
        
        dpm = np.array([[0.0,0.0,0.0]])
        dpm_lst = np.zeros((dxdy.shape[0],2))
        yaws = np.cumsum(dr)
        yaws = yaws - (yaws//(np.pi*2))*(np.pi*2)

        for i in range(1,clip.shape[0]):
            
            cur_pos = np.zeros((1,3))
            cur_pos[0,0] = dxdy[i,0]
            cur_pos[0,2] = dxdy[i,1]
            dpm += np.dot(cur_pos,rot(yaws[i]))
            dpm_lst[i,0] = copy.deepcopy(dpm[0,0])
            dpm_lst[i,1] = copy.deepcopy(dpm[0,2])
        
        # Plot the data
        ax.plot(dpm_lst[:,0], dpm_lst[:,1], 'b-', linewidth=2, c=cmap(map_idxs[ic]))
    if save_path:
        plt.savefig(save_path)
    else:
        plt.show()
    return 
            
def viz_jnt_index(jnt_frame):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    ax.set_xlabel('$X$')
    ax.set_ylabel('$Y$')
    ax.set_zlabel('$Z$')

    for i in range(jnt_frame.shape[0]):
        plt.text(jnt_frame[:,0],jnt_frame[:,1],jnt_frame[:,2],{}.format(i))

