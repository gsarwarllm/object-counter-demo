#!/usr/bin/env bash
# Download the SSD MobileNet v2 (COCO) model into the layout TF Serving expects:
#   tmp/model/ssd_mobilenet_v2/1/saved_model.pb
# Safe to re-run: skips the download when the model is already there.
set -euo pipefail

MODEL_DIR="tmp/model/ssd_mobilenet_v2/1"
MODEL_URL="http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v2_coco_2018_03_29.tar.gz"
ARCHIVE_NAME="ssd_mobilenet_v2_coco_2018_03_29"

if [ -f "$MODEL_DIR/saved_model.pb" ]; then
    echo "Model already present at $MODEL_DIR, skipping download."
    exit 0
fi

mkdir -p "$MODEL_DIR"
curl -fL --progress-bar -o tmp/model.tar.gz "$MODEL_URL"
tar -xzf tmp/model.tar.gz -C tmp/model
mv "tmp/model/$ARCHIVE_NAME/saved_model/saved_model.pb" "$MODEL_DIR/"
rm -rf tmp/model.tar.gz "tmp/model/$ARCHIVE_NAME"
# TF Serving runs as a different user inside the container.
chmod -R a+rX tmp/model
echo "Model ready at $MODEL_DIR."
