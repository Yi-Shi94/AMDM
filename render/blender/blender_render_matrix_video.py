#########################################################################
# Example run:
# blender -b -P jingbo_render.py -- root_path output_path
#########################################################################
import collections
import math
import os
import pathlib
import pickle
import sys

import bpy
import mathutils

import numpy as np

# Parse args if in bg mode.
# if bpy.app.background:
#     args = sys.argv[sys.argv.index("--") + 1:]
#     root_path = args[0]
#     output_path = args[1]
# else:
root_path = '/home/admin1/workspace/simulation/pacer_plus_results/demo_update_1/'
output_path = '/home/admin1/workspace/simulation/pacer_plus_results/demo_update_1_render'

os.makedirs(output_path, exist_ok=True)
mesh_files = sorted(list(pathlib.Path(root_path).rglob('*.ply')))
frames = len(mesh_files)
# with open(os.path.join(root_path, 'camera_info_motion_0.pkl'), 'rb') as f:
#     data = pickle.load(f)

# Set up rendering.
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.device = 'GPU'
#bpy.context.scene.cycles.samples = 64
bpy.context.scene.cycles.samples = 32
bpy.context.scene.render.resolution_x = 1080
bpy.context.scene.render.resolution_y = 720
bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.cycles.use_denoising = True

# Delete objects.
for obj in bpy.context.scene.objects:
    obj.select_set(True)

bpy.ops.object.delete()

for mat in bpy.data.materials:
    bpy.data.materials.remove(mat)

bpy.data.collections.remove(bpy.data.collections['Collection'])

# Set up world nodes.
skytex_node = bpy.context.scene.world.node_tree.nodes.new('ShaderNodeTexSky')
bg_node = bpy.context.scene.world.node_tree.nodes['Background']
bpy.context.scene.world.node_tree.links.new(skytex_node.outputs['Color'], bg_node.inputs['Color'])

bg_node.inputs['Strength'].default_value = 0.1
skytex_node.sky_type = 'NISHITA'
skytex_node.sun_elevation = 45 * math.pi / 180
skytex_node.sun_rotation = -225 * math.pi / 180
skytex_node.air_density = 0.1
skytex_node.dust_density = 0.1
skytex_node.ozone_density = 6.0

# Set up materials.
#colors = sns.color_palette('Paired', 25)
colors = [
    (0.6509803921568628, 0.807843137254902, 0.8901960784313725),
    (0.12156862745098039, 0.47058823529411764, 0.7058823529411765),
    (0.6980392156862745, 0.8745098039215686, 0.5411764705882353),
    (0.2, 0.6274509803921569, 0.17254901960784313),
    (0.984313725490196, 0.6039215686274509, 0.6),
    (0.8901960784313725, 0.10196078431372549, 0.10980392156862745),
    (0.9921568627450981, 0.7490196078431373, 0.43529411764705883),
    (1.0, 0.4980392156862745, 0.0),
    (0.792156862745098, 0.6980392156862745, 0.8392156862745098),
    (0.41568627450980394, 0.23921568627450981, 0.6039215686274509),
    (1.0, 1.0, 0.6),
    (0.6941176470588235, 0.34901960784313724, 0.1568627450980392),
    (0.6509803921568628, 0.807843137254902, 0.8901960784313725),
    (0.12156862745098039, 0.47058823529411764, 0.7058823529411765),
    (0.6980392156862745, 0.8745098039215686, 0.5411764705882353),
    (0.2, 0.6274509803921569, 0.17254901960784313),
    (0.984313725490196, 0.6039215686274509, 0.6),
    (0.8901960784313725, 0.10196078431372549, 0.10980392156862745),
    (0.9921568627450981, 0.7490196078431373, 0.43529411764705883),
    (1.0, 0.4980392156862745, 0.0),
    (0.792156862745098, 0.6980392156862745, 0.8392156862745098),
    (0.41568627450980394, 0.23921568627450981, 0.6039215686274509),
    (1.0, 1.0, 0.6),
    (0.6941176470588235, 0.34901960784313724, 0.1568627450980392),
    (0.6509803921568628, 0.807843137254902, 0.8901960784313725)]
mats = []
for i, color in enumerate(colors):
    mat = bpy.data.materials.new(name=f'mat{i}')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.distribution = 'MULTI_GGX'
    bsdf.subsurface_method = 'RANDOM_WALK'
    bsdf.inputs['Base Color'].default_value = color + (1.0,)
    bsdf.inputs['Roughness'].default_value = 0.9
    mats.append(mat)
print(len(mats))
terrain_mat = bpy.data.materials.new(name='terrain')
terrain_mat.use_nodes = True
bsdf = terrain_mat.node_tree.nodes['Principled BSDF']
bsdf.distribution = 'MULTI_GGX'
bsdf.subsurface_method = 'RANDOM_WALK'
bsdf.inputs['Base Color'].default_value = (0.001, 0.001, 0.001, 1.0)
bsdf.inputs['Roughness'].default_value = 0.4

plane_mat = bpy.data.materials.new(name='plane')
plane_mat.use_nodes = True
bsdf = plane_mat.node_tree.nodes['Principled BSDF']
bsdf.distribution = 'MULTI_GGX'
bsdf.subsurface_method = 'RANDOM_WALK'
bsdf.inputs['Base Color'].default_value = (0.05, 0.05, 0.05, 1.0)
bsdf.inputs['Roughness'].default_value = 0.4
gradtex_node = plane_mat.node_tree.nodes.new('ShaderNodeTexGradient')
gradtex_node.gradient_type = 'SPHERICAL'
plane_mat.node_tree.links.new(gradtex_node.outputs['Color'], bsdf.inputs['Base Color'])

# Import the people meshes.
meshes = collections.defaultdict(dict)
for mesh_file in mesh_files:
    if mesh_file.stem.startswith('terrain'):
        continue
    col_name = str(mesh_file.parent.relative_to(root_path))
    if col_name not in bpy.context.scene.collection.children:
        col = bpy.data.collections.new(col_name)
        bpy.context.scene.collection.children.link(col)
    else:
        col = bpy.context.scene.collection.children[col_name]
    bpy.ops.import_mesh.ply(filepath=str(mesh_file))
    mesh_obj = bpy.context.selected_objects[0]
    for old_col in mesh_obj.users_collection:
        old_col.objects.unlink(mesh_obj)
    col.objects.link(mesh_obj)
    mesh_id = int(mesh_file.stem)
    mesh_obj.name = f'mesh{mesh_id:03d}'
    bpy.ops.object.shade_smooth()
    mat_index = int(mesh_file.parent.name)
    mat = mats[mat_index]
    mesh_obj.data.materials.append(mat)
    mesh_obj.hide_viewport = True
    mesh_obj.hide_render = True
    location = mesh_obj.location
    mesh_obj.location = (location[0], location[1], location[2] + 10)
    meshes[col_name][mesh_id] = mesh_obj

# Import the terrain mesh.
bpy.ops.import_mesh.ply(filepath=os.path.join(root_path, 'terrain.ply'))
terrain_obj = bpy.context.selected_objects[0]
terrain_obj.name = 'terrain'
location = terrain_obj.location
terrain_obj.location = (location[0], location[1], location[2] + 9.97)
bpy.ops.object.shade_smooth()
terrain_obj.data.materials.append(terrain_mat)


# Add cameras.
# cam_data = bpy.data.cameras.new('camera')
# cam = bpy.data.objects.new('camera', cam_data)
# cam.location = (23.965, -24.06, 28.432)
# cam.rotation_mode='XYZ'
# cam.rotation_euler = (77.6/60, 0, -0)
# bpy.context.scene.collection.objects.link(cam)
# bpy.context.scene.camera = cam

# demo 1
cam_data = bpy.data.cameras.new('camera')
cam = bpy.data.objects.new('camera', cam_data)
cam.location = (41.334, 9.7335, 17.005)
cam.rotation_mode='XYZ'
cam.rotation_euler = (math.pi * (90/180), 0, math.pi * (90/180))
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam

# demo 2
# cam_data = bpy.data.cameras.new('camera')
# cam = bpy.data.objects.new('camera', cam_data)
# cam.location = (6.07696, 6.77777 , 21.4791)
# cam.rotation_mode='XYZ'
# cam.rotation_euler = (math.pi * (78/180), 0, math.pi * (-78/180))
# bpy.context.scene.collection.objects.link(cam)
# bpy.context.scene.camera = cam


# demo 3
# cam_data = bpy.data.cameras.new('camera')
# cam = bpy.data.objects.new('camera', cam_data)
# cam.location = (7.85469, 19.8559, 21.936)
# cam.rotation_mode='XYZ'
# cam.rotation_euler = (math.pi * (70/180), 0, math.pi * (-66/180))
# bpy.context.scene.collection.objects.link(cam)
# bpy.context.scene.camera = cam

# demo 4
# cam_data = bpy.data.cameras.new('camera')
# cam = bpy.data.objects.new('camera', cam_data)
# cam.location = (34.9982, 36.052, 20.1993 )
# cam.rotation_mode='XYZ'
# cam.rotation_euler = (math.pi * (63/180), 0, math.pi * (112/180))
# bpy.context.scene.collection.objects.link(cam)
# bpy.context.scene.camera = cam


keys = [k for k in meshes.keys()]
for frame in range(0, 600, 2):
    for key in keys:
        if frame in meshes[key]:
            mesh_obj = meshes[key][frame]
            mesh_obj.hide_viewport = False
            mesh_obj.hide_render = False
    bpy.context.scene.render.filepath = os.path.join(output_path, f'{frame//2:03d}.png')
    bpy.ops.render.render(write_still=1)
    for key in keys:
        if frame in meshes[key]:
            mesh_obj = meshes[key][frame]
            mesh_obj.hide_viewport = True
            mesh_obj.hide_render = True
