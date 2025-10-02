import os
import shutil
import json
import bpy
import mathutils
from . import helper, blender_nerf_operator

# global addon script variables
EMPTY_NAME = 'BlenderNeRF Sphere'
CAMERA_NAME = 'BlenderNeRF Camera'


class MatrixCameraRender(blender_nerf_operator.BlenderNeRF_Operator):
    '''Matrix Camera Render Operator'''
    bl_idname = 'object.matrix_camera_render'
    bl_label = 'Matrix Camera Render'

    def load_transforms_data(self, scene):
        """Load transform metadata from the path defined on the scene."""
        transforms_path = getattr(scene, 'mat_transforms_path', '')

        if not transforms_path:
            self.report({'ERROR'}, 'Matrix transforms path not set!')
            return False

        if not os.path.exists(transforms_path):
            self.report({'ERROR'}, f'Transforms file not found: {transforms_path}')
            return False

        try:
            with open(transforms_path, 'r') as file_handle:
                self.transforms_data = json.load(file_handle)

            frames_count = len(self.transforms_data.get('frames', []))
            scene.mat_nb_frames = frames_count
            return True

        except json.JSONDecodeError as exc:
            self.report({'ERROR'}, f'JSON parsing error: {exc}')
            return False
        except Exception as exc:
            self.report({'ERROR'}, f'Error loading transforms file: {exc}')
            return False

    def apply_camera_intrinsics(self, scene, camera, transforms_data):
        """Update the Blender camera intrinsics using values from transforms data."""
        if not transforms_data:
            self.report({'WARNING'}, 'Transforms data not loaded.')
            return False

        try:
            camera_angle_x = transforms_data.get('camera_angle_x', camera.data.angle_x)
            camera_angle_y = transforms_data.get('camera_angle_y', camera.data.angle_y)
            fl_x = transforms_data.get('fl_x')
            w = transforms_data.get('w')

            if fl_x and w:
                focal_length_mm = (fl_x * 36) / w  # Assume a 36 mm reference sensor width.
                camera.data.lens = focal_length_mm
            scene.render.resolution_x = int(transforms_data.get('w', scene.render.resolution_x))
            scene.render.resolution_y = int(transforms_data.get('h', scene.render.resolution_y))
            camera.data.angle_x = camera_angle_x
            camera.data.angle_y = camera_angle_y
            
            return True

        except Exception as exc:
            self.report({'ERROR'}, f'Error applying camera intrinsics: {exc}')
            return False

    def transforms_camera_update(self, scene, frame_index):
        """Apply the transform matrix at the given frame index to the helper camera."""
        if not hasattr(self, 'transforms_data') or not self.transforms_data:
            return False

        try:
            frames = self.transforms_data.get('frames', [])
            if frame_index >= len(frames):
                return False

            frame_data = frames[frame_index]
            transform_matrix = frame_data.get('transform_matrix')

            if not transform_matrix:
                return False

            matrix = mathutils.Matrix(transform_matrix)

            if CAMERA_NAME in scene.objects:
                camera_obj = scene.objects[CAMERA_NAME]
                camera_obj.matrix_world = matrix
                return True

            return False

        except Exception as exc:
            return False

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        if camera is None:
            self.report({'ERROR'}, 'Be sure to have a selected camera!')
            return {'FINISHED'}

        error_messages = self.asserts(scene, method='MAT')
        if error_messages:
            self.report({'ERROR'}, error_messages[0])
            return {'FINISHED'}

        if not self.load_transforms_data(scene):
            return {'FINISHED'}

        output_data = self.get_camera_intrinsics(scene, camera)

        output_dir = bpy.path.clean_name(scene.mat_dataset_name)
        output_path = os.path.join(scene.save_path, output_dir)
        os.makedirs(output_path, exist_ok=True)
        
        if scene.logs: 
            self.save_log_file(scene, output_path, camera, method='MAT')
        if scene.splats: 
            self.save_splats_ply(scene, output_path)

        # initial property might have changed since set_init_props update
        scene.init_output_path = scene.render.filepath

        # other intial properties
        scene.init_sphere_exists = scene.show_sphere
        scene.init_camera_exists = scene.show_camera
        scene.init_frame_end = scene.frame_end
        scene.init_active_camera = camera

        if scene.test_data:
            if hasattr(self, 'transforms_data') and self.transforms_data:
                output_data['frames'] = []
                for index, frame_data in enumerate(self.transforms_data.get('frames', [])):
                    frame_info = {
                        'file_path': os.path.join('train', f'frame_{index + 1:05d}.png'),
                        'transform_matrix': frame_data.get('transform_matrix', [])
                    }
                    output_data['frames'].append(frame_info)
            else:
                output_data['frames'] = self.get_camera_extrinsics(scene, camera, mode='TEST', method='MAT')

            self.save_json(output_path, 'transforms_test.json', output_data)

        if scene.train_data:
            if not scene.show_camera:
                scene.show_camera = True

            sphere_camera = scene.objects[CAMERA_NAME]
            sphere_output_data = self.get_camera_intrinsics(scene, sphere_camera)
            scene.camera = sphere_camera

            if not self.apply_camera_intrinsics(scene, sphere_camera, getattr(self, 'transforms_data', {})):
                self.report({'WARNING'}, 'Failed to apply camera intrinsics from transforms data.')

            frames = getattr(self, 'transforms_data', {}).get('frames', [])
            frames_count = len(frames)
            scene.mat_nb_frames = frames_count
            scene.frame_end = scene.frame_start + max(frames_count - 1, 0)

            sphere_output_data['frames'] = []
            for index, frame_data in enumerate(frames):
                frame_info = {
                    'file_path': os.path.join('train', f'frame_{index + 1:05d}.png'),
                    'transform_matrix': frame_data.get('transform_matrix', [])
                }
                sphere_output_data['frames'].append(frame_info)

            self.save_json(output_path, 'transforms_train.json', sphere_output_data)

            if scene.render_frames:
                output_train = os.path.join(output_path, 'train')
                os.makedirs(output_train, exist_ok=True)
                scene.rendering = (False, False, False, True)
                scene.frame_end = scene.frame_start + max(scene.mat_nb_frames - 1, 0)

                if frames:
                    self.transforms_camera_update(scene, 0)

                helper.register_matrix_handler(scene, self.transforms_camera_update)

                scene.render.use_compositing = True
                scene.render.use_sequencer = False
                scene.use_nodes = True
                tree = scene.node_tree
                nodes = tree.nodes
                nodes.clear()

                rl_node = nodes.new('CompositorNodeRLayers')
                rl_node.scene = scene

                rgb_output_node = nodes.new('CompositorNodeOutputFile')
                rgb_output_node.base_path = os.path.join(output_train, '')
                rgb_output_node.file_slots[0].path = 'frame_#####'

                tree.links.new(rl_node.outputs['Image'], rgb_output_node.inputs[0])

                if scene.render_mask:
                    mask_output_train = os.path.join(output_path, 'mask')
                    os.makedirs(mask_output_train, exist_ok=True)
                    
                    scene.view_layers["ViewLayer"].use_pass_object_index = True
                    
                    # Initialize object pass indices for mask rendering.
                    for obj in bpy.data.objects:
                        obj.pass_index = 1

                    # Clear the helper objects from the mask output.
                    objects_to_exclude = [EMPTY_NAME, CAMERA_NAME]
                    for obj in bpy.data.objects:
                        if obj.name in objects_to_exclude:
                            obj.pass_index = 0
                            
                    # Add the ID Mask node and target the pass index value of 1.
                    id_mask_node = nodes.new('CompositorNodeIDMask')
                    id_mask_node.index = 1  # Object pass index
                    
                    # Create a file output node for masks.
                    mask_output_node = nodes.new('CompositorNodeOutputFile')
                    mask_output_node.base_path = mask_output_train
                    mask_output_node.file_slots[0].path = "frame_#####"
                    mask_output_node.format.file_format = 'PNG'
                    mask_output_node.format.color_depth = '8'
                    mask_output_node.format.color_mode = 'BW'
                    
                    # Write 8-bit grayscale PNG masks.
                    tree.links.new(rl_node.outputs['IndexOB'], id_mask_node.inputs[0])
                    tree.links.new(id_mask_node.outputs[0], mask_output_node.inputs[0])
                    
                if scene.render_depth:
                    depth_output_train = os.path.join(output_path, 'depth')
                    os.makedirs(depth_output_train, exist_ok=True)
                    
                    scene.view_layers["ViewLayer"].use_pass_z = True

                    # Create a file output node for depth maps.
                    depth_output_node = nodes.new('CompositorNodeOutputFile')
                    depth_output_node.base_path = depth_output_train
                    depth_output_node.file_slots[0].path = "frame_#####"
                    depth_output_node.format.file_format = 'PNG'
                    depth_output_node.format.color_depth = '16'
                    depth_output_node.format.color_mode = 'BW'

                    # Normalize depth values to the 0-1 range.
                    normalize_node = nodes.new('CompositorNodeNormalize')
                    
                    # Emit 16-bit grayscale PNG files.
                    tree.links.new(rl_node.outputs['Depth'], normalize_node.inputs[0])
                    tree.links.new(normalize_node.outputs[0], depth_output_node.inputs[0])
                    
                if scene.render_depth_exr:
                    depth_exr_output_train = os.path.join(output_path, 'depth_exr')
                    os.makedirs(depth_exr_output_train, exist_ok=True)
                    
                    scene.view_layers["ViewLayer"].use_pass_z = True

                    # Output depth data as 32-bit float EXR files.
                    depth_exr_output_node = nodes.new('CompositorNodeOutputFile')
                    depth_exr_output_node.base_path = depth_exr_output_train
                    depth_exr_output_node.file_slots[0].path = "frame_#####"
                    depth_exr_output_node.format.file_format = 'OPEN_EXR'
                    depth_exr_output_node.format.color_depth = '32'
                    depth_exr_output_node.format.color_mode = 'BW'
                    tree.links.new(rl_node.outputs['Depth'], depth_exr_output_node.inputs[0])
                    
                if scene.render_normal:
                    normal_output_train = os.path.join(output_path, 'normal')
                    os.makedirs(normal_output_train, exist_ok=True)

                    scene.view_layers["ViewLayer"].use_pass_normal = True
                    
                    # Create a PNG output node for normal maps.
                    normal_png_node = nodes.new('CompositorNodeOutputFile')
                    normal_png_node.base_path = normal_output_train
                    normal_png_node.file_slots[0].path = "frame_#####"
                    normal_png_node.format.file_format = 'PNG'
                    normal_png_node.format.color_depth = '8'
                    normal_png_node.format.color_mode = 'RGB'

                    # Export 8-bit RGB PNG normal maps.
                    tree.links.new(rl_node.outputs['Normal'], normal_png_node.inputs[0])
                    
                if scene.render_normal_exr:
                    normal_exr_output_train = os.path.join(output_path, 'normal_exr')
                    os.makedirs(normal_exr_output_train, exist_ok=True)

                    scene.view_layers["ViewLayer"].use_pass_normal = True
                    
                    # Output normal data as 32-bit float EXR files.
                    normal_exr_node = nodes.new('CompositorNodeOutputFile')
                    normal_exr_node.base_path = normal_exr_output_train
                    normal_exr_node.file_slots[0].path = "frame_#####"
                    normal_exr_node.format.file_format = 'OPEN_EXR'
                    normal_exr_node.format.color_depth = '32'
                    normal_exr_node.format.color_mode = 'RGB'
                    tree.links.new(rl_node.outputs['Normal'], normal_exr_node.inputs[0])

                bpy.ops.render.render('INVOKE_DEFAULT', animation=True, write_still=True)

                helper.unregister_matrix_handler()
                scene.rendering = (False, False, False, False)

        if not any(scene.rendering):
            helper.unregister_matrix_handler()

            if not scene.init_camera_exists: helper.delete_camera(scene, CAMERA_NAME)
            if not scene.init_sphere_exists:
                objects = bpy.data.objects
                if EMPTY_NAME in objects:
                    objects.remove(objects[EMPTY_NAME], do_unlink=True)
                scene.show_sphere = False
                scene.sphere_exists = False

            scene.camera = scene.init_active_camera
            scene.render.filepath = scene.init_output_path

            # compress dataset and remove folder (only keep zip)
            shutil.make_archive(output_path, 'zip', output_path) # output filename = output_path
            shutil.rmtree(output_path)

        return {'FINISHED'}
