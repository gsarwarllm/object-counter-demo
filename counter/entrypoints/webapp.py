from io import BytesIO

from flask import Flask, request, jsonify

from counter import config
from counter.domain.errors import ValidationError, InvalidImageError
from counter.entrypoints.schemas import parse_predictions_request, to_predictions_response_dto

def create_app():

    app = Flask(__name__)

    object_detector = config.get_object_detector()
    count_action = config.get_count_action(object_detector)
    detect_action = config.get_detect_action(object_detector)

    @app.route('/object-count', methods=['POST'])
    def object_detection():

        threshold = float(request.form.get('threshold', 0.5))
        uploaded_file = request.files['file']
        image = BytesIO()
        uploaded_file.save(image)
        count_response = count_action.execute(image, threshold)
        return jsonify(count_response)

    @app.route('/object-predictions', methods=['POST'])
    def object_predictions():
        predictions_request = parse_predictions_request(request.form, request.files)
        predictions = detect_action.execute(predictions_request.image, predictions_request.threshold)
        return jsonify(to_predictions_response_dto(predictions_request.threshold, predictions))

    @app.errorhandler(ValidationError)
    def handle_validation_error(error):
        return problem_response(400, 'Invalid request', 'Request validation failed',
                                errors=[{'field': error.field, 'message': error.message}])

    @app.errorhandler(InvalidImageError)
    def handle_invalid_image_error(error):
        return problem_response(400, 'Invalid image', str(error))

    return app


def problem_response(status, title, detail, errors=None):
    body = {'type': 'about:blank', 'title': title, 'status': status, 'detail': detail, 'instance': request.path}
    if errors:
        body['errors'] = errors
    response = jsonify(body)
    response.status_code = status
    response.mimetype = 'application/problem+json'
    return response

if __name__ == '__main__':
    app = create_app()
    app.run('0.0.0.0', debug=True)
