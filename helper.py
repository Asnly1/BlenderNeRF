import os
import shutil
import random
import math
import mathutils
import bpy
from bpy.app.handlers import persistent


# global addon script variables
EMPTY_NAME = 'BlenderNeRF Sphere'
CAMERA_NAME = 'BlenderNeRF Camera'

_matrix_frame_handler = None
_matrix_handler_scene = None

## property poll and update functions

# camera pointer property poll function
def poll_is_camera(self, obj):
    return obj.type == 'CAMERA'

def visualize_sphere(self, context):
    scene = context.scene

    if EMPTY_NAME not in scene.objects.keys() and not scene.sphere_exists:
        # if empty sphere does not exist, create
        bpy.ops.object.empty_add(type='SPHERE') # non default location, rotation and scale here are sometimes not applied, so we enforce them manually below
        empty = context.active_object
        empty.name = EMPTY_NAME
        empty.location = scene.sphere_location
        empty.rotation_euler = scene.sphere_rotation
        empty.scale = scene.sphere_scale
        empty.empty_display_size = scene.sphere_radius

        scene.sphere_exists = True

    elif EMPTY_NAME in scene.objects.keys() and scene.sphere_exists:
        if CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
            delete_camera(scene, CAMERA_NAME)

        objects = bpy.data.objects
        objects.remove(objects[EMPTY_NAME], do_unlink=True)

        scene.sphere_exists = False

def visualize_camera(self, context):
    scene = context.scene

    if CAMERA_NAME not in scene.objects.keys() and not scene.camera_exists:
        if EMPTY_NAME not in scene.objects.keys():
            scene.show_sphere = True

        bpy.ops.object.camera_add()
        camera = context.active_object
        camera.name = CAMERA_NAME
        camera.data.name = CAMERA_NAME
        camera.location = sample_from_sphere(scene)
        bpy.data.cameras[CAMERA_NAME].lens = scene.focal

        cam_constraint = camera.constraints.new(type='TRACK_TO')
        cam_constraint.track_axis = 'TRACK_Z' if scene.outwards else 'TRACK_NEGATIVE_Z'
        cam_constraint.up_axis = 'UP_Y'
        cam_constraint.target = bpy.data.objects[EMPTY_NAME]

        scene.camera_exists = True

    elif CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
        objects = bpy.data.objects
        objects.remove(objects[CAMERA_NAME], do_unlink=True)

        for block in bpy.data.cameras:
            if CAMERA_NAME in block.name:
                bpy.data.cameras.remove(block)

        scene.camera_exists = False

def delete_camera(scene, name):
    objects = bpy.data.objects
    objects.remove(objects[name], do_unlink=True)

    scene.show_camera = False
    scene.camera_exists = False

    for block in bpy.data.cameras:
        if name in block.name:
            bpy.data.cameras.remove(block)

# non uniform sampling when stretched or squeezed sphere
def sample_from_sphere(scene):
    seed = (2654435761 * (scene.seed + 1)) ^ (805459861 * (scene.frame_current + 1))
    rng = random.Random(seed) # random number generator

    # sample random angles
    theta = rng.random() * 2 * math.pi
    phi = math.acos(1 - 2 * rng.random()) # ensure uniform sampling from unit sphere

    # uniform sample from unit sphere, given theta and phi
    unit_x = math.cos(theta) * math.sin(phi)
    unit_y = math.sin(theta) * math.sin(phi)
    unit_z = abs( math.cos(phi) ) if scene.upper_views else math.cos(phi)
    unit = mathutils.Vector((unit_x, unit_y, unit_z))

    # ellipsoid sample : center + rotation @ radius * unit sphere
    point = scene.sphere_radius * mathutils.Vector(scene.sphere_scale) * unit
    rotation = mathutils.Euler(scene.sphere_rotation).to_matrix()
    point = mathutils.Vector(scene.sphere_location) + rotation @ point

    return point


def register_matrix_handler(scene, update_callback):
    """Register a frame-change handler that replays matrix transforms for matrix renders."""
    global _matrix_frame_handler, _matrix_handler_scene

    unregister_matrix_handler()

    _matrix_handler_scene = scene

    def _matrix_frame_change(frame_scene, depsgraph):
        if frame_scene != _matrix_handler_scene:
            return

        frame_index = frame_scene.frame_current - frame_scene.frame_start
        try:
            update_callback(frame_scene, frame_index)
        except Exception as exc:
            print(f"Matrix handler error: {exc}")

    _matrix_frame_handler = _matrix_frame_change
    bpy.app.handlers.frame_change_pre.append(_matrix_frame_change)
    if cos_camera_update in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(cos_camera_update)


def unregister_matrix_handler():
    """Remove any registered matrix frame-change handler."""
    global _matrix_frame_handler, _matrix_handler_scene

    if _matrix_frame_handler and _matrix_frame_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_matrix_frame_handler)

    _matrix_frame_handler = None
    _matrix_handler_scene = None
    if cos_camera_update not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(cos_camera_update)


def configure_auxiliary_outputs(scene, tree, rl_node, output_root):
    """Set up optional mask/depth/normal outputs based on scene toggles."""
    # Mask output
    if scene.render_mask:
        mask_output = os.path.join(output_root, 'mask')
        os.makedirs(mask_output, exist_ok=True)

        scene.view_layers['ViewLayer'].use_pass_object_index = True

        for obj in bpy.data.objects:
            obj.pass_index = 1

        for helper_name in (EMPTY_NAME, CAMERA_NAME):
            if helper_name in bpy.data.objects:
                bpy.data.objects[helper_name].pass_index = 0

        id_mask_node = tree.nodes.new('CompositorNodeIDMask')
        id_mask_node.index = 1

        mask_output_node = tree.nodes.new('CompositorNodeOutputFile')
        mask_output_node.base_path = mask_output
        mask_output_node.file_slots[0].path = 'frame_#####'
        mask_output_node.format.file_format = 'PNG'
        mask_output_node.format.color_depth = '8'
        mask_output_node.format.color_mode = 'BW'

        tree.links.new(rl_node.outputs['IndexOB'], id_mask_node.inputs[0])
        tree.links.new(id_mask_node.outputs[0], mask_output_node.inputs[0])

    # Depth PNG output
    if scene.render_depth:
        depth_output = os.path.join(output_root, 'depth')
        os.makedirs(depth_output, exist_ok=True)

        scene.view_layers['ViewLayer'].use_pass_z = True

        depth_output_node = tree.nodes.new('CompositorNodeOutputFile')
        depth_output_node.base_path = depth_output
        depth_output_node.file_slots[0].path = 'frame_#####'
        depth_output_node.format.file_format = 'PNG'
        depth_output_node.format.color_depth = '16'
        depth_output_node.format.color_mode = 'BW'

        normalize_node = tree.nodes.new('CompositorNodeNormalize')

        tree.links.new(rl_node.outputs['Depth'], normalize_node.inputs[0])
        tree.links.new(normalize_node.outputs[0], depth_output_node.inputs[0])

    # Depth EXR output
    if scene.render_depth_exr:
        depth_exr_output = os.path.join(output_root, 'depth_exr')
        os.makedirs(depth_exr_output, exist_ok=True)

        scene.view_layers['ViewLayer'].use_pass_z = True

        depth_exr_node = tree.nodes.new('CompositorNodeOutputFile')
        depth_exr_node.base_path = depth_exr_output
        depth_exr_node.file_slots[0].path = 'frame_#####'
        depth_exr_node.format.file_format = 'OPEN_EXR'
        depth_exr_node.format.color_depth = '32'
        depth_exr_node.format.color_mode = 'BW'

        tree.links.new(rl_node.outputs['Depth'], depth_exr_node.inputs[0])

    # Normal PNG output
    if scene.render_normal:
        normal_output = os.path.join(output_root, 'normal')
        os.makedirs(normal_output, exist_ok=True)

        scene.view_layers['ViewLayer'].use_pass_normal = True

        normal_png_node = tree.nodes.new('CompositorNodeOutputFile')
        normal_png_node.base_path = normal_output
        normal_png_node.file_slots[0].path = 'frame_#####'
        normal_png_node.format.file_format = 'PNG'
        normal_png_node.format.color_depth = '8'
        normal_png_node.format.color_mode = 'RGB'

        tree.links.new(rl_node.outputs['Normal'], normal_png_node.inputs[0])

    # Normal EXR output
    if scene.render_normal_exr:
        normal_exr_output = os.path.join(output_root, 'normal_exr')
        os.makedirs(normal_exr_output, exist_ok=True)

        scene.view_layers['ViewLayer'].use_pass_normal = True

        normal_exr_node = tree.nodes.new('CompositorNodeOutputFile')
        normal_exr_node.base_path = normal_exr_output
        normal_exr_node.file_slots[0].path = 'frame_#####'
        normal_exr_node.format.file_format = 'OPEN_EXR'
        normal_exr_node.format.color_depth = '32'
        normal_exr_node.format.color_mode = 'RGB'

        tree.links.new(rl_node.outputs['Normal'], normal_exr_node.inputs[0])


def update_multi_level_frames(self, context):
    """Update the total frame count based on multi-level settings"""
    scene = context.scene
    if scene.use_multi_level and scene.horizontal_movement:
        # 计算总帧数
        total_frames = scene.frames_1 + scene.frames_2 + scene.frames_3
        
        # 更新frame_end
        scene.frame_end = scene.frame_start + total_frames - 1
        
        # 关键修改：同时更新cos_nb_frames
        scene.cos_nb_frames = total_frames

## two way property link between sphere and ui (property and handler functions)
# https://blender.stackexchange.com/questions/261174/2-way-property-link-or-a-filtered-property-display

def properties_ui_upd(self, context):
    can_scene_upd(self, context)

@persistent
def properties_desgraph_upd(scene):
    can_properties_upd(scene)

def properties_ui(self, context):
    scene = context.scene

    if EMPTY_NAME in scene.objects.keys():
        upd_off()
        bpy.data.objects[EMPTY_NAME].location = scene.sphere_location
        bpy.data.objects[EMPTY_NAME].rotation_euler = scene.sphere_rotation
        bpy.data.objects[EMPTY_NAME].scale = scene.sphere_scale
        bpy.data.objects[EMPTY_NAME].empty_display_size = scene.sphere_radius
        upd_on()

    if CAMERA_NAME in scene.objects.keys():
        upd_off()
        bpy.data.cameras[CAMERA_NAME].lens = scene.focal
        if 'Track To' in bpy.context.scene.objects[CAMERA_NAME].constraints:
            bpy.context.scene.objects[CAMERA_NAME].constraints['Track To'].track_axis = 'TRACK_Z' if scene.outwards else 'TRACK_NEGATIVE_Z'
        upd_on()

# if empty sphere modified outside of ui panel, edit panel properties
def properties_desgraph(scene):
    if scene.show_sphere and EMPTY_NAME in scene.objects.keys():
        upd_off()
        scene.sphere_location = bpy.data.objects[EMPTY_NAME].location
        scene.sphere_rotation = bpy.data.objects[EMPTY_NAME].rotation_euler
        scene.sphere_scale = bpy.data.objects[EMPTY_NAME].scale
        scene.sphere_radius = bpy.data.objects[EMPTY_NAME].empty_display_size
        upd_on()

    if scene.show_camera and CAMERA_NAME in scene.objects.keys():
        upd_off()
        scene.focal = bpy.data.cameras[CAMERA_NAME].lens
        if 'Track To' in bpy.context.scene.objects[CAMERA_NAME].constraints:
            scene.outwards = (bpy.context.scene.objects[CAMERA_NAME].constraints['Track To'].track_axis == 'TRACK_Z')
        upd_on()

    if EMPTY_NAME not in scene.objects.keys() and scene.sphere_exists:
        if CAMERA_NAME in scene.objects.keys() and scene.camera_exists:
            delete_camera(scene, CAMERA_NAME)

        scene.show_sphere = False
        scene.sphere_exists = False

    if CAMERA_NAME not in scene.objects.keys() and scene.camera_exists:
        scene.show_camera = False
        scene.camera_exists = False

        for block in bpy.data.cameras:
            if CAMERA_NAME in block.name:
                bpy.data.cameras.remove(block)

    if CAMERA_NAME in scene.objects.keys():
        scene.objects[CAMERA_NAME].location = sample_from_sphere(scene)

def empty_fn(self, context): pass

can_scene_upd = properties_ui
can_properties_upd = properties_desgraph

def upd_off():  # make sub function to an empty function
    global can_scene_upd, can_properties_upd
    can_scene_upd = empty_fn
    can_properties_upd = empty_fn
def upd_on():
    global can_scene_upd, can_properties_upd
    can_scene_upd = properties_ui
    can_properties_upd = properties_desgraph


## blender handler functions

# reset properties back to intial
@persistent
def post_render(scene):
    if any(scene.rendering): # execute this function only when rendering with addon
        dataset_names = (
            scene.sof_dataset_name,
            scene.ttc_dataset_name,
            scene.cos_dataset_name,
            scene.mat_dataset_name
        )
        method_dataset_name = dataset_names[list(scene.rendering).index(True)]

        if scene.rendering[0]: scene.frame_step = scene.init_frame_step # sof : reset frame step

        if scene.rendering[1]: # ttc : reset frame end
            scene.frame_end = scene.init_frame_end

        if scene.rendering[2]: # cos : reset camera settings
            if not scene.init_camera_exists: delete_camera(scene, CAMERA_NAME)
            if not scene.init_sphere_exists:
                objects = bpy.data.objects
                objects.remove(objects[EMPTY_NAME], do_unlink=True)
                scene.show_sphere = False
                scene.sphere_exists = False

            scene.camera = scene.init_active_camera
            scene.frame_end = scene.init_frame_end

        if scene.rendering[3]: # mat : reset camera reference only
            scene.camera = scene.init_active_camera
            scene.frame_end = scene.init_frame_end
            unregister_matrix_handler()

        if scene.node_tree:
            scene.node_tree.nodes.clear()
        scene.use_nodes = False
        scene.render.use_compositing = False

        scene.rendering = (False, False, False, False)
        scene.render.filepath = scene.init_output_path # reset filepath

        # clean directory name (unsupported characters replaced) and output path
        output_dir = bpy.path.clean_name(method_dataset_name)
        output_path = os.path.join(scene.save_path, output_dir)

        if scene.compress_dataset and os.path.isdir(output_path):
            shutil.make_archive(output_path, 'zip', output_path) # output filename = output_path
            shutil.rmtree(output_path)

# set initial property values (bpy.data and bpy.context require a loaded scene)
@persistent
def set_init_props(scene):
    filepath = bpy.data.filepath
    filename = bpy.path.basename(filepath)
    default_save_path = filepath[:-len(filename)] # remove file name from blender file path = directoy path

    scene.save_path = default_save_path
    scene.init_frame_step = scene.frame_step
    scene.init_output_path = scene.render.filepath

    bpy.app.handlers.depsgraph_update_post.remove(set_init_props)

# Function to calculate a point on the sphere at a specific z-level and angle
def calculate_horizontal_point(scene, z_level, angle_degrees):
    # Convert angle from degrees to radians
    angle_radians = math.radians(angle_degrees)
    
    # Get sphere parameters
    r = scene.sphere_radius
    
    # Calculate z-coordinate based on z_level (-1.0 to 1.0)
    z = z_level * r
    
    # Calculate the radius at this z-level using the circle-sphere intersection formula
    # For a sphere of radius r at z-level, the radius of the circle is sqrt(r^2 - z^2)
    if abs(z) > r:
        # If z is outside the sphere, clamp it to the sphere boundary
        z = r if z > 0 else -r
        horizontal_radius = 0
    else:
        horizontal_radius = math.sqrt(r**2 - z**2)
    
    # Calculate x and y coordinates based on the angle
    x = horizontal_radius * math.cos(angle_radians)
    y = horizontal_radius * math.sin(angle_radians)
    
    # Apply scaling
    scale = mathutils.Vector(scene.sphere_scale)
    scaled_point = mathutils.Vector((
        scale[0] * x,
        scale[1] * y,
        scale[2] * z
    ))
    
    # Apply rotation
    rotation = mathutils.Euler(scene.sphere_rotation).to_matrix()
    rotated_point = rotation @ scaled_point
    
    # Apply translation
    final_point = mathutils.Vector(scene.sphere_location) + rotated_point
    
    return final_point

# Update the cos_camera_update function to include horizontal movement
@persistent
def cos_camera_update(scene):
    """Update camera position based on frame, either sequentially (spiral), randomly (sphere), or horizontally with multiple z-levels."""
    if CAMERA_NAME in scene.objects.keys():
        if scene.render_sequential:
            # Existing spiral path logic
            frame = scene.frame_current
            total_frames = scene.cos_nb_frames
            
            # 定义螺旋参数
            r = scene.sphere_radius  # 使用 sphere_radius 作为终止高度
            omega = 2.0  # 旋转速度
            
            # 计算 θ，范围 [0, π]
            theta = (math.pi * frame) / total_frames
            
            # 计算半径，保持在0.67r到1.0r之间，使其始终在中间1/3的球面上
            # sin(theta)的范围是0到1，这里我们把它映射到0.67到1.0之间
            radius_factor = 0.67 + 0.33 * math.sin(theta)
            radius = radius_factor * r
            
            # 使用lowest_level和highest_level来计算高度范围
            # 将theta从[0, π]映射到[lowest_level, highest_level]
            z_min = scene.lowest_level * r
            z_max = scene.highest_level * r
            z_range = z_max - z_min
            
            # 计算高度
            if scene.upper_views:  # 如果只需要上半部分视角
                # 映射到[0, z_max]或指定范围的上半部分
                z = z_min + z_range * (theta / math.pi)
            else:
                # 在整个指定范围内映射
                z = z_min + z_range * (theta / math.pi)
            # 计算旋转角度
            phi = omega * theta
            
            # 计算基础螺旋坐标
            x = radius * math.cos(phi)
            y = radius * math.sin(phi)
            
            # 应用缩放变换
            scale = mathutils.Vector(scene.sphere_scale)
            scaled_point = mathutils.Vector((
                scale[0] * x,
                scale[1] * y,
                scale[2] * z
            ))
            
            # 应用旋转变换
            rotation = mathutils.Euler(scene.sphere_rotation).to_matrix()
            rotated_point = rotation @ scaled_point
            
            # 应用平移变换
            final_point = mathutils.Vector(scene.sphere_location) + rotated_point
            
            # 更新相机位置
            scene.objects[CAMERA_NAME].location = final_point
            
            # 确保相机朝向场景中心
            center = mathutils.Vector(scene.sphere_location)
            direction = center - final_point
            # 计算旋转四元数
            rot_quat = direction.to_track_quat('-Z', 'Y')
            scene.objects[CAMERA_NAME].rotation_euler = rot_quat.to_euler()
        elif scene.render_sequential and scene.horizontal_movement:
            # Get current frame (relative to start frame)
            rel_frame = scene.frame_current - scene.frame_start
            
            if scene.use_multi_level:
                # Determine which z-level to use based on frame count
                if rel_frame < scene.frames_1:
                    # First z-level
                    current_z_level = scene.z_level_1
                    level_start = 0
                    level_frames = scene.frames_1
                elif rel_frame < scene.frames_1 + scene.frames_2:
                    # Second z-level
                    current_z_level = scene.z_level_2
                    level_start = scene.frames_1
                    level_frames = scene.frames_2
                else:
                    # Third z-level
                    current_z_level = scene.z_level_3
                    level_start = scene.frames_1 + scene.frames_2
                    level_frames = scene.frames_3
                
                # Calculate relative frame within this level
                level_rel_frame = rel_frame - level_start
                
                # Calculate angle for this level (0-360 degrees for each level)
                angle = (360.0 * level_rel_frame) / level_frames
            else:
                # Original single z-level logic
                current_z_level = scene.z_level
                angle = (360.0 * rel_frame) / scene.cos_nb_frames
            
            # Calculate position on sphere at specified z-level and angle
            position = calculate_horizontal_point(scene, current_z_level, angle)
            
            # Update camera position
            scene.objects[CAMERA_NAME].location = position
            
            # Make camera look at center of sphere
            center = mathutils.Vector(scene.sphere_location)
            direction = center - position
            
            # Set camera rotation
            if scene.outwards:
                # If outwards is enabled, flip the direction
                direction = -direction
            
            # Calculate rotation quaternion
            rot_quat = direction.to_track_quat('-Z', 'Y')
            scene.objects[CAMERA_NAME].rotation_euler = rot_quat.to_euler()
        else:
            # 原有的球面随机采样逻辑
            scene.objects[CAMERA_NAME].location = sample_from_sphere(scene)
