# SmartThumb SA - Test Cases

Run `python tools/make_test_images.py` to generate the files. "Actual" columns are filled from real runs (do not pre-fill).

| ID | Requirement | Input (tests/test_images/) | Expected | Automated test | Actual (AWS) |
|----|-------------|----------------------------|----------|----------------|--------------|
| TC01 | FR1-FR4 | `handbag_01.jpg` (4000×3000) | `thumbnails/handbag_01_thumb.jpg`, 300×225 | test_thumbnail_max_300… | |
| TC02 | FR3 | `shoes_02.jpg` (3024×4032 portrait) | 225×300 | same | |
| TC03 | FR3 | `panorama_05.jpg` (6000×1200) | 300×60 | same | |
| TC04 | FR3 | `tall_06.jpg` (1000×5000) | 60×300 | same | |
| TC05 | FR1 | `gift_04.JPG` (uppercase ext) | processed | test_happy_path | |
| TC06 | FR3 | `transparent_08.png` | PNG with alpha kept | test_png_alpha_preserved | |
| TC07 | FR3 | `small_09.jpg` (200×150) | not upscaled | test_small_image_not_upscaled | |
| TC08 | FR3 | `rotated_exif_25.jpg` | upright thumbnail | test_exif_rotation_applied | |
| TC09 | FR1 | `png_named_jpg_26.jpg` | processed as PNG | test_png_with_jpg_extension… | |
| TC10 | FR2 | any valid upload, no manual invoke | Lambda runs automatically (CloudWatch entry) | n/a (cloud) | |
| TC11 | FR7 | `INVALID_not_an_image.jpg` | `rejected unreadable_image`, no thumbnail | test_invalid_files_rejected… | |
| TC12 | FR7 | `INVALID_empty.png` | `rejected empty_file` | same | |
| TC13 | FR7 | `INVALID_truncated.jpg` | rejected, no crash | same | |
| TC14 | FR7 | `INVALID_animated.gif`, `INVALID_notes.txt`, `INVALID_document.pdf` | `rejected unsupported_extension` | same | |
| TC15 | NFR | upload to output bucket | event ignored (no loop) | test_recursion_guard | |
| TC16 | NFR | key with spaces (`my shoes/red bag.jpg`) | correct decode and output key | test_url_encoded_key_decoded | |
| TC17 | NFR | same upload twice | one thumbnail, no duplicates | test_duplicate_events_idempotent | |
| TC18 | NFR | S3 throttling error | exception raised → Lambda retry | test_transient_s3_error… | n/a |
| TC19 | FR5 | real product photo, Rekognition on | `labels/*.json` with suggestions | test_labels_written… | |
| TC20 | FR5 | Rekognition denied/failing | thumbnail still created, `labels_failed` logged | test_rekognition_failure… | |
| TC21 | FR6 | all runs | CloudWatch shows success and rejection lines | n/a | |
| TC22 | NFR | try public access to a thumbnail URL | AccessDenied | manual | |
