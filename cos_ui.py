import bpy


# camera on sphere ui class
class COS_UI(bpy.types.Panel):
    '''Camera on Sphere UI'''
    bl_idname = 'VIEW3D_PT_cos_ui'
    bl_label = 'Camera on Sphere COS'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderNeRF'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.alignment = 'CENTER'

        layout.use_property_split = True
        layout.prop(scene, 'camera')
        layout.prop(scene, 'sphere_location')
        layout.prop(scene, 'sphere_rotation')
        layout.prop(scene, 'sphere_scale')
        layout.prop(scene, 'sphere_radius')
        layout.prop(scene, 'focal')
        layout.prop(scene, 'seed')

        layout.prop(scene, 'cos_nb_frames')
        layout.prop(scene, 'upper_views', toggle=True)
        layout.prop(scene, 'outwards', toggle=True)
        layout.prop(scene, 'render_mask', toggle=True)
        layout.prop(scene, 'render_depth', toggle=True)
        layout.prop(scene, 'render_depth_exr', toggle=True)
        layout.prop(scene, 'render_normal', toggle=True)
        layout.prop(scene, 'render_normal_exr', toggle=True)
        layout.prop(scene, 'render_sequential', toggle=True)
        if scene.render_sequential:
            layout.prop(scene, 'horizontal_movement', toggle=True)
            
        if not scene.horizontal_movement:
            layout.prop(scene, 'lowest_level')
            layout.prop(scene, 'highest_level')
        
        if scene.horizontal_movement:
            layout.prop(scene, 'z_level')
                
            layout.prop(scene, 'use_multi_level', toggle=True)
            if scene.use_multi_level:
                layout.prop(scene, 'z_level_1')
                layout.prop(scene, 'frames_1')
                layout.prop(scene, 'z_level_2')
                layout.prop(scene, 'frames_2')                
                layout.prop(scene, 'z_level_3')
                layout.prop(scene, 'frames_3')

        layout.use_property_split = False
        layout.separator()
        layout.label(text='Preview')

        row = layout.row(align=True)
        row.prop(scene, 'show_sphere', toggle=True)
        row.prop(scene, 'show_camera', toggle=True)

        layout.separator()
        layout.use_property_split = True
        layout.prop(scene, 'cos_dataset_name')

        layout.separator()
        layout.operator('object.camera_on_sphere', text='PLAY COS')