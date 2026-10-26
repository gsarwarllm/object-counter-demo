class ValidationError(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class InvalidImageError(Exception):
    pass


class RepositoryUnavailableError(Exception):
    """The count store can't be reached (connection refused, timeout, ...)."""
