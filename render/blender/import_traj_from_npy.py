import bpy
import numpy as np


path = "/home/sy/repo/AMDM-public/output/inpaint/amdm_style100_traj/out_angle_0_traj.npy"

control_points = np.load(path)

# List of 3D coordinates for the Bezier curve
bpy.ops.curve.primitive_bezier_curve_add()

curve = bpy.context.active_object
curve.data.bevel_depth = 40
bez_points = curve.data.splines[0].bezier_points

# note: a created bezier curve has already 2 control points
bez_points.add(len(control_points) - 2)

# now copy the csv data
for i in range(len(control_points)):   
    cur_point = control_points[i]
    cur_point[...,[0,2,1]] = cur_point[...,[0,1,2]]
    #cur_point[...,:2] *= 100
    cur_point[...,1] *= -1
    cur_point[...,2] *= 0
    bez_points[i].co = cur_point #* 100
    bez_points[i].handle_left_type  = 'FREE'
    bez_points[i].handle_right_type = 'FREE'
           
    # just for illustration (screenshot),
    # add your correct handle locations here
    bez_points[i].handle_left  = control_points[i]
    bez_points[i].handle_right = control_points[i]