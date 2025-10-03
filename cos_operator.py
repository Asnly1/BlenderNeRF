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

        if scene.logs: self.save_log_file(scene, output_path, camera, method='COS')
        if scene.splats: self.save_splats_ply(scene, output_path)

        # initial property might have changed since set_init_props update
        scene.init_output_path = scene.render.filepath

        # other intial properties
        scene.init_sphere_exists = scene.show_sphere
        scene.init_camera_exists = scene.show_camera
        scene.init_frame_end = scene.frame_end
        scene.init_active_camera = camera

        if scene.test_data:
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
                
                helper.configure_auxiliary_outputs(scene, tree, rl_node, output_path)

                bpy.ops.render.render('INVOKE_DEFAULT', animation=True, write_still=True) # render scene

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

            if scene.compress_dataset and os.path.isdir(output_path):
                shutil.make_archive(output_path, 'zip', output_path)
                shutil.rmtree(output_path)

        return {'FINISHED'}
