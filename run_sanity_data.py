import numpy as np
import dataset.lafan1_dataset as lafan1_dataset
import dataset.dataset_builder as dataset_builder
import dataset.util.plot as plot_util


def get_data_from_dataset():
    #config_file = 'config/model/amdm_lafan1_single.yaml'
    config_file = 'config/model/amdm_lafan1.yaml'
    #config_file = 'output/base/amdm_lafan1/config.yaml'
    dataset = dataset_builder.build_dataset(config_file)
    #dataset.motion_flattened = dataset.load_new_data()

    num_frame = 300
    data_frames = np.zeros((num_frame, dataset.frame_dim))
    # FK: https://github.com/facebookresearch/fairmotion/blob/main/fairmotion/data/bvh.py
    for i in range(num_frame): 
        # 代码 dataset.util.bvh
        #data_frames[i][1:,2] = rad_root 
        #data_frames[i][1:,:2] = dxdy_root 
        #data_frames[i][:,3:3+3*njoint] = joint_positions 
        #data_frames[i][1:,3+3*njoint:3+6*njoint] = joint_velocities  
        #data_frames[i][:,3+6*njoint:3+12*njoint] = joint_orientations 
        data_frames[i] = dataset[i][0]
    
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
    

    #PLOT ALTOGETHER
    jnt_pos = np.array([data_frames_jnts_position0, data_frames_jnts_position1, data_frames_jnts_position2, data_frames_jnts_position2])
    
    num_char = jnt_pos.shape[0]
    num_frame = jnt_pos.shape[1]
    num_jnt = jnt_pos.shape[2]
    jnt_pos = jnt_pos.transpose(1,0,2,3).reshape(num_frame, -1, jnt_pos.shape[3])
    links = np.concatenate([np.array(dataset.links) + j*num_jnt for j in range(num_char)],axis=0)
    color_map = ['r','g', 'b', 'yellow']
    colors =  [color_map[j] for j in range(num_char) for _ in dataset.links]
    plot_util.plot_lafan1(jnt_pos, links, colors=colors) 


if __name__ == '__main__':
    get_data_from_dataset()
    

