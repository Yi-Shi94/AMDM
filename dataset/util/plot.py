
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import torch
import numpy as np
import matplotlib.cm as cm

def plot_multiple(jnts_multiple, links_single, plot_fn, fps, save_path):
    assert len(jnts_multiple.shape) == 4, 'wrong dimension for multple char plotting'
    num_char, num_frame, num_jnt, num_dim = jnts_multiple.shape

    jnts_multiple = jnts_multiple.transpose(1,0,2,3).reshape(num_frame, -1, num_dim)
    links = np.concatenate([np.array(links_single) + j*num_jnt for j in range(num_char)],axis=0)
    color_map = ['r','g', 'b', 'yellow', 'magenta','tan','cyan','yellowgreen', 'm', 'k']
    colors =  [color_map[j] for j in range(num_char) for _ in links_single]
    plot_fn(jnts_multiple, links, fps, save_path, colors=colors) 


def plot_jnt_vel(jnts_multiple, links_single, plot_fn, fps, save_path):
    assert len(jnts_multiple.shape) == 4, 'wrong dimension for multple char plotting'
    num_char, num_frame, num_jnt, num_dim = jnts_multiple.shape

    jnts_multiple = jnts_multiple[:-1,...]
    jnts_multiple = jnts_multiple.transpose(1,0,2,3).reshape(num_frame, -1, num_dim)
    #links = np.concatenate([np.array(links_single) + j*num_jnt for j in range(num_char)],axis=0)
    
    links = np.concatenate([np.array(links_single) + j*num_jnt for j in range(num_char-1)],axis=0)
    #print(jnts_multiple.shape, links.shape)
    color_map = ['r','g', 'b', 'yellow', 'magenta','tan','cyan','yellowgreen', 'm', 'k']
    colors =  [color_map[j] for j in range(num_char-1) for _ in links_single]
    plot_fn(jnts_multiple, links, fps, save_path, colors=colors) 


def plot_traj_amass(clips, save_path=None):
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    cmap = cm.get_cmap('Spectral')
    
    if len(clips.shape)==2:
        ax.plot(clips[:,0,0], clips[:,0,1], linewidth=2, c=cmap(0.1))
    else:
        map_idxs = list(np.arange(0,len(clips))/len(clips))
        for ic in range(clips.shape[0]):
            c  = 'b' if ic == 0 else cmap(map_idxs[ic])
            lw = 4 if ic ==0 else 2
            ax.plot(clips[ic,:,0,0], clips[ic,:,0,1],  linewidth=lw, c=c)

    if save_path:
        plt.savefig(save_path)
    else:
        plt.show()
    return 

def plot_traj_lafan1(clips, save_path=None):
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    cmap = cm.get_cmap('Spectral')
    
    if len(clips.shape)==2:
        ax.plot(clips[:,0,0], clips[:,0,2], linewidth=2, c=cmap(0.1))
    else:
        map_idxs = list(np.arange(0,len(clips))/len(clips))
        for ic in range(clips.shape[0]):
            c  = 'black' if ic == 0 else cmap(map_idxs[ic])
            lw = 2.5 if ic ==0 else 2
            ax.plot(clips[ic,:,0,0], clips[ic,:,0,2], linewidth=lw, c=c)

    if save_path:
        plt.savefig(save_path)
    else:
        plt.show()
    return 

def plot_lafan1(x, links, fps=30, save_path=None, colors = None):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    if isinstance(x, torch.Tensor):
        x = x.cpu().detach().numpy()

    link_data = np.zeros((len(links),x.shape[0]-1,3,2))
    xini = x[0]

    if colors is None:
        link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,2],xini[ed,2]],[xini[st,1],xini[ed,1]],color='r')[0]
                    for st,ed in links]
    else:
        link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,2],xini[ed,2]],[xini[st,1],xini[ed,1]],color=colors[j])[0]
                    for j,(st,ed) in enumerate(links)]

    ax.set_xlabel('$X$')
    ax.set_ylabel('$Y$')
    ax.set_zlabel('$Z$')
    ax.set_xlim(-1, +1)
    ax.set_ylim(-1, +1)
    ax.set_zlim(0,2)

    for i in range(1,x.shape[0]):
        for j,(st,ed) in enumerate(links):
            pt_st = x[i-1,st] #- y_rebase
            pt_ed = x[i-1,ed] #- y_rebase
            link_data[j,i-1,:,0] = pt_st
            link_data[j,i-1,:,1] = pt_ed
            
    def update_links(num, data_lst, obj_lst):
        cur_data_lst = data_lst[:,num,:,:] 
        cur_root = cur_data_lst[0,:,0]

        root_x = cur_root[0]
        root_y = cur_root[2]
        for obj, data in zip(obj_lst, cur_data_lst):
            obj.set_data(data[[0,2],:])
            obj.set_3d_properties(data[1,:])

            ax.set_xlim(root_x-1, root_x+1)
            ax.set_ylim(root_y-1, root_y+1)
            ax.set_zlim(0,2)
    
    line_ani = animation.FuncAnimation(fig, update_links, x.shape[0]-1, fargs=(link_data, link_obj),
                            interval=30, blit=False)
    if save_path is not None:
        writergif = animation.PillowWriter(fps=fps) 
        line_ani.save(save_path+'.gif', writer=writergif)

    if save_path is None:
        plt.show()
    plt.close()

def plot_amass(x, links, fps=30, save_path=None, colors = None):
    
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    if isinstance(x, torch.Tensor):
        x = x.cpu().detach().numpy()

    link_data = np.zeros((len(links),x.shape[0]-1,3,2))
    xini = x[0]
    if colors is None:
        link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,1],xini[ed,1]],[xini[st,2],xini[ed,2]],color='r')[0]
                    for st,ed in links]
    else:
        link_obj = [ax.plot([xini[st,0],xini[ed,0]],[xini[st,1],xini[ed,1]],[xini[st,2],xini[ed,2]],color=colors[j])[0]
                    for j,(st,ed) in enumerate(links)]

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
        cur_root = cur_data_lst[0,:,0]

        root_x = cur_root[0]
        root_y = cur_root[1]
        for obj, data in zip(obj_lst, cur_data_lst):
            obj.set_data(data[[0,1],:])
            obj.set_3d_properties(data[2,:])

            ax.set_xlim(root_x-1, root_x+1)
            ax.set_ylim(root_y-1, root_y+1)
            ax.set_zlim(0,2)
    
    line_ani = animation.FuncAnimation(fig, update_links, x.shape[0]-1, fargs=(link_data, link_obj),
                            interval=30, blit=False)
    if save_path is not None:
        writergif = animation.PillowWriter(fps=fps) 
        line_ani.save(save_path+'.gif', writer=writergif)

    if save_path is None:
        plt.show()
    plt.close()


