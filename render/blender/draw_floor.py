import bpy

def create_grid_floor(size, spacing):
    # Create a new mesh
    bpy.ops.mesh.primitive_grid_add(size=size, scale=(spacing, spacing, 1))

    # Rename the object
    grid_object = bpy.context.active_object
    grid_object.name = "GridFloor"

    # Set the location of the grid to (0, 0, 0)
    grid_object.location = (0, 0, 0)

    return grid_object

# Clear existing mesh objects
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.object.select_by_type(type='MESH')
bpy.ops.object.delete()

# Set the size and spacing of the grid
grid_size = 10
grid_spacing = 1

# Create the grid floor
grid_floor = create_grid_floor(grid_size, grid_spacing)
