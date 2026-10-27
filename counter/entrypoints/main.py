import json
import sys
from dataclasses import asdict

from counter import config
from counter.domain.actions import CountDetectedObjects
from counter.logging_config import configure_logging

USAGE = "usage: python -m counter.entrypoints.main <image_path> <threshold> [model_name]"

if __name__ == "__main__":
    configure_logging()
    if len(sys.argv) not in (3, 4):
        sys.exit(USAGE)
    img_path, threshold = sys.argv[1], float(sys.argv[2])
    detectors = config.get_detector_registry()
    model = detectors.get(sys.argv[3] if len(sys.argv) == 4 else None)
    action = CountDetectedObjects(
        model.detector, config.get_count_repo(), config.get_debug_image_writer()
    )
    with open(img_path, "rb") as img:
        count_response = action.execute(img, threshold)
    # The CLI's output is the JSON response, the same shape as POST /object-count.
    output = {**asdict(count_response), "model": {"name": model.name, "version": model.version}}
    print(json.dumps(output, indent=2))
