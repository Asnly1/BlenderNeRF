import os
import shutil
import bpy
from . import helper, blender_nerf_operator
import json


# global addon script variables
EMPTY_NAME = 'BlenderNeRF Sphere'
CAMERA_NAME = 'BlenderNeRF Camera'

# Camera-on-sphere operator class
class CameraOnSphere(blender_nerf_operator.BlenderNeRF_Operator):
    '''Camera on Sphere Operator'''
    bl_idname = 'object.camera_on_sphere'
    bl_label = 'Camera on Sphere COS'

    def load_existing_transforms_data(self, file_path):
        """Read extrinsic matrices stored in an existing transforms file."""
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    return data.get('frames', [])
            return None
        except Exception as e:
            return None

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        # check if camera is selected : next errors depend on an existing camera
        if camera == None:
            self.report({'ERROR'}, 'Be sure to have a selected camera!')
            return {'FINISHED'}

        # if there is an error, print first error message
        error_messages = self.asserts(scene, method='COS')
        if len(error_messages) > 0:
            self.report({'ERROR'}, error_messages[0])
            return {'FINISHED'}

        output_data = self.get_camera_intrinsics(scene, camera)

        # clean directory name (unsupported characters replaced) and output path
        output_dir = bpy.path.clean_name(scene.cos_dataset_name)
        output_path = os.path.join(scene.save_path, output_dir)
        os.makedirs(output_path, exist_ok=True)

        if scene.logs: self.save_log_file(scene, output_path, method='COS')
        if scene.splats: self.save_splats_ply(scene, output_path)

        # initial property might have changed since set_init_props update
        scene.init_output_path = scene.render.filepath

        # other intial properties
        scene.init_sphere_exists = scene.show_sphere
        scene.init_camera_exists = scene.show_camera
        scene.init_frame_end = scene.frame_end
        scene.init_active_camera = camera

        if scene.test_data:
            # Attempt to load extrinsics from an existing transforms_test.json.
            test_json = getattr(scene, 'mat_transforms_path', '')
            existing_frames = self.load_existing_transforms_data(test_json)
            
            if existing_frames:
                output_data['frames'] = []
                for index, frame_data in enumerate(existing_frames.get('frames', [])):
                    frame_info = {
                        'file_path': os.path.join('test', f'frame_{index + 1:05d}.png'),
                        'transform_matrix': frame_data.get('transform_matrix', [])
                    }
                    output_data['frames'].append(frame_info)
            else:
                # Fallback to generating extrinsics within Blender if no cache is found.
                output_data['frames'] = self.get_camera_extrinsics(scene, camera, mode='TEST', method='COS')
            
            self.save_json(output_path, 'transforms_test.json', output_data)

        if scene.train_data:
            if not scene.show_camera: scene.show_camera = True

            # train camera on sphere
            sphere_camera = scene.objects[CAMERA_NAME]
            sphere_output_data = self.get_camera_intrinsics(scene, sphere_camera)
            scene.camera = sphere_camera

            # training transforms
            sphere_output_data['frames'] = self.get_camera_extrinsics(scene, sphere_camera, mode='TRAIN', method='COS')
            self.save_json(output_path, 'transforms_train.json', sphere_output_data)

            # rendering
            if scene.render_frames:
                output_train = os.path.join(output_path, 'train')
                os.makedirs(output_train, exist_ok=True)
                scene.rendering = (False, False, True, False)
                scene.frame_end = scene.frame_start + scene.cos_nb_frames - 1 # update end frame

                # Enable the compositor and clear existing nodes.
                scene.render.use_compositing = True
                scene.render.use_sequencer = False
                scene.use_nodes = True
                tree = scene.node_tree
                nodes = tree.nodes
                nodes.clear()
                
                # Add the render layer node for the current scene.
                rl_node = nodes.new('CompositorNodeRLayers')
                rl_node.scene = scene

                # Create a file output node for RGB exports.
                rgb_output_node = nodes.new('CompositorNodeOutputFile')
                rgb_output_node.base_path = os.path.join(output_train, '')
                rgb_output_node.file_slots[0].path = "frame_#####"
                
                # Route the output into the RGB file sequence.
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

                bpy.ops.render.render('INVOKE_DEFAULT', animation=True, write_still=True) # render scene
                scene.rendering = (False, False, False, False)

        # if frames are rendered, the below code is executed by the handler function
        if not any(scene.rendering):
            # reset camera settings
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