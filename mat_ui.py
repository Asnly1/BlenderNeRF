import bpy


# matrix camera render ui class
class MAT_UI(bpy.types.Panel):
    '''Matrix Camera Render UI'''
    bl_idname = 'VIEW3D_PT_mat_ui'
    bl_label = 'Camera Specified by Matrix'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderNeRF'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.alignment = 'CENTER'

        layout.separator()
        layout.label(text='Preview')

        row = layout.row(align=True)
        row.prop(scene, 'show_sphere', toggle=True)
        row.prop(scene, 'show_camera', toggle=True)
        
        layout.use_property_split = True
        layout.prop(scene, 'mat_dataset_name')

        layout.separator()
        layout.operator('object.matrix_camera_render', text='PLAY MAT')
