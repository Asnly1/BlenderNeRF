# Feature Summary vs 30e6691d

## 1. Matrix-driven camera capture

- Added `matrix_operator.MatrixCameraRender` that ingests external `transforms.json` files, restores camera intrinsics, and batches train/test exports.
- Introduced the `MAT_UI` panel and new scene properties (`mat_dataset_name`, `mat_transforms_path`, `mat_nb_frames`) plus a shortcut in the main panel to configure the matrix path.
- Extended `helper` with frame handlers (`register_matrix_handler` / `unregister_matrix_handler`) so matrices are replayed per frame and helper objects are cleaned up after rendering.

## 2. Rich auxiliary render outputs

- All SOF/TTC/COS/MAT operators rebuild the compositor tree and call `helper.configure_auxiliary_outputs` to export RGB alongside Mask, Depth (PNG/EXR), and Normal (PNG/EXR).
- Added `render_mask`, `render_depth`, `render_depth_exr`, `render_normal`, and `render_normal_exr` toggles that appear only when frame rendering is enabled.
- Normalized training image naming to `frame_#####`, keeping JSON metadata and filenames perfectly aligned.

## 3. Expanded COS camera paths

- Introduced `render_sequential` for spiral sweeps across the sphere, with `lowest_level` / `highest_level` limiting the altitude range.
- Added `horizontal_movement` and optional `use_multi_level` controls to orbit at one or three configurable z-levels with per-level frame counts.
- Reworked `helper.cos_camera_update` with new helpers (`calculate_horizontal_point`, `update_multi_level_frames`) to drive the new trajectories.

## 4. Reusable test transforms and richer logs

- `mat_transforms_path` now feeds SOF/TTC/COS test exports, ensuring all modes share the same extrinsics when an external cache exists.
- `save_log_file` accepts a camera reference and, when `log_intrinsic` is enabled, writes the full intrinsic matrix alongside mode-specific metadata.

## 5. Controlled clean-up and packaging

- Added a `compress_dataset` toggle so users decide whether to zip and purge the dataset directory once rendering finishes.
- Expanded the `scene.rendering` state vector to four entries, covering the MAT mode, and tightened `post_render` clean-up to restore cameras, compositor nodes, and file paths consistently.
