import numpy as np
import dataset.lafan1_dataset as style100_dataset
import dataset.dataset_builder as dataset_builder
import dataset.util.plot as plot_util


def get_data_from_dataset():
    #config_file = 'config/model/amdm_style100_single_cond.yaml'
    config_file = 'config/model/amdm_humanml3d.yaml'
    dataset = dataset_builder.build_dataset(config_file, 'cpu')

    num_frame = 200
    data_frames = np.zeros((num_frame, dataset.frame_dim))
    # FK: https://github.com/facebookresearch/fairmotion/blob/main/fairmotion/data/bvh.py
    for i in range(num_frame): 
        # 代码 dataset.util.bvh
        #data_frames[i][1:,2] = rad_root 把上一帧的heading置零，这一帧heading的变化，（一帧内root绕z轴的旋转）
        #data_frames[i][1:,:2] = dxdy_root 把上一帧的heading置零，这一帧root的x y方向的位移 
        #data_frames[i][:,3:3+3*njoint] = joint_positions 这一帧关节点位置 （root位于原点）
        #data_frames[i][1:,3+3*njoint:3+6*njoint] = joint_velocities  这一帧关节点的速度
        #data_frames[i][:,3+6*njoint:3+12*njoint] = joint_orientations 这一帧关节局部旋转6d表示（3x3旋转矩阵的前两行）
        #data, _ = dataset[i]
        data = dataset[i]
        data_frames[i] = data[0]

    data_frames_denormalized = dataset.denorm_data(data_frames) #代码 dataset.base_dataset.denorm_data
    #data_frames_denormalized是[Frame * X]的数组 

    data_frames_jnts_position0 = dataset.x_to_jnts(data_frames_denormalized, mode='position') #代码 dataset.base_dataset.lafan1_dataset.x_to_jnts
    print("joint:")
    plot_util.plot_lafan1(data_frames_jnts_position0, dataset.links)
    
    #FK 
    data_frames_jnts_position1 = dataset.x_to_jnts(data_frames_denormalized, mode='angle') #FK  dataset.base_dataset.lafan1_dataset.x_to_jnts
    print("fk:")
    plot_util.plot_lafan1(data_frames_jnts_position1, dataset.links)

    #VELOCITY
    data_frames_jnts_position2 = dataset.x_to_jnts(data_frames_denormalized, mode='velocity') #frame(x) = frame(x-1)+delta(x-1)  dataset.base_dataset.lafan1_dataset.x_to_jnts
    print("vel:")
    plot_util.plot_lafan1(data_frames_jnts_position2, dataset.links)
    
    #IK THEN FK
    #TODO BINGKUN
    data_frames_jnts_position3 = dataset.x_to_jnts(data_frames_denormalized, mode='ik_fk') #FK  dataset.base_dataset.lafan1_dataset.x_to_jnts
    print("ikfk:")
    plot_util.plot_lafan1(data_frames_jnts_position3, dataset.links)
    
    #PLOT ALTOGETHER
    jnt_pos = np.array([data_frames_jnts_position0, data_frames_jnts_position1, data_frames_jnts_position2, data_frames_jnts_position3])
    
    num_char = jnt_pos.shape[0]
    num_frame = jnt_pos.shape[1]
    num_jnt = jnt_pos.shape[2]
    jnt_pos = jnt_pos.transpose(1,0,2,3).reshape(num_frame, -1, jnt_pos.shape[3])
    links = np.concatenate([np.array(dataset.links) + j*num_jnt for j in range(num_char)],axis=0)
    color_map = ['r','g', 'b', 'yellow']
    colors =  [color_map[j] for j in range(num_char) for _ in dataset.links]
    plot_util.plot_lafan1(jnt_pos, links, colors=colors) # 骨骼结构 dataset.util.skeleton_info.py


if __name__ == '__main__':
    get_data_from_dataset()
    
