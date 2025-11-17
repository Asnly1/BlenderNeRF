import os
import shutil
import bpy
from . import blender_nerf_operator, helper


# subset of frames operator class
class SubsetOfFrames(blender_nerf_operator.BlenderNeRF_Operator):
    '''Subset of Frames Operator'''
    bl_idname = 'object.subset_of_frames'
    bl_label = 'Subset of Frames SOF'

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        # check if camera is selected : next errors depend on an existing camera
        if camera == None:
            self.report({'ERROR'}, 'Be sure to have a selected camera!')
            return {'FINISHED'}

        # if there is an error, print first error message
        error_messages = self.asserts(scene, method='SOF')
        if len(error_messages) > 0:
           self.report({'ERROR'}, error_messages[0])
           return {'FINISHED'}

        output_data = self.get_camera_intrinsics(scene, camera)

        # clean directory name (unsupported characters replaced) and output path
        output_dir = bpy.path.clean_name(scene.sof_dataset_name)
        output_path = os.path.join(scene.save_path, output_dir)
        os.makedirs(output_path, exist_ok=True)

        if scene.logs: self.save_log_file(scene, output_path, camera, method='SOF')
        if scene.splats: self.save_splats_ply(scene, output_path)

        # initial properties might have changed since set_init_props update
        scene.init_frame_step = scene.frame_step
        scene.init_output_path = scene.render.filepath

        if scene.test_data:
            output_frames = None
            test_json = getattr(scene, 'mat_transforms_path', '')
            if test_json:
                existing_data = self.load_existing_transforms_data(test_json)
                if existing_data:
                    existing_frames = existing_data.get('frames', [])
                    output_frames = []
                    for index, frame_data in enumerate(existing_frames):
                        frame_info = {
                            'file_path': os.path.join('test', f'frame_{index + 1:05d}.png'),
                            'transform_matrix': frame_data.get('transform_matrix', [])
                        }
                        output_frames.append(frame_info)

            if output_frames is None:
                output_frames = self.get_camera_extrinsics(scene, camera, mode='TEST', method='SOF')

            output_data['frames'] = output_frames
            self.save_json(output_path, 'transforms_test.json', output_data)

        if scene.train_data:
            # training transforms
            output_data['frames'] = self.get_camera_extrinsics(scene, camera, mode='TRAIN', method='SOF')
            self.save_json(output_path, 'transforms_train.json', output_data)

            # rendering
            if scene.render_frames:
                output_train = os.path.join(output_path, 'train')
                os.makedirs(output_train, exist_ok=True)
                scene.rendering = (True, False, False, False)
                scene.frame_step = scene.train_frame_steps

                tree = helper.prepare_compositor(scene)
                nodes = tree.nodes

                rl_node = nodes.new('CompositorNodeRLayers')
                rl_node.scene = scene
                helper.mark_temp_node(scene, rl_node)

                rgb_output_node = nodes.new('CompositorNodeOutputFile')
                helper.mark_temp_node(scene, rgb_output_node)
                rgb_output_node.base_path = os.path.join(output_train, '')
                rgb_output_node.file_slots[0].path = 'frame_#####'

                tree.links.new(rl_node.outputs['Image'], rgb_output_node.inputs[0])
                helper.configure_auxiliary_outputs(scene, tree, rl_node, output_path)

                bpy.ops.render.render('INVOKE_DEFAULT', animation=True, write_still=True)

        # if frames are rendered, the below code is executed by the handler function
        if not any(scene.rendering):
            if scene.compress_dataset and os.path.isdir(output_path):
                shutil.make_archive(output_path, 'zip', output_path)
                shutil.rmtree(output_path)

        return {'FINISHED'}
