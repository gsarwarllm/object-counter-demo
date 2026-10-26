class ValidationError(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class InvalidImageError(Exception):
    pass
