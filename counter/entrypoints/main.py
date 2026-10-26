import json
import logging
import sys
from dataclasses import asdict

from counter import config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    img_path = sys.argv[1]
    threshold = float(sys.argv[2])
    with open(img_path, "rb") as img:
        count_response = config.get_count_action().execute(img, threshold)
    # The CLI's output is the JSON response, the same shape as POST /object-count.
    print(json.dumps(asdict(count_response), indent=2))
