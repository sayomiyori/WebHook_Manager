class PlatformError(Exception):
    """Static boundary error; never retain remote responses or credentials."""

    def __init__(self, status_code: int = 503) -> None:
        self.status_code = status_code
        message = {
            400: "Invalid Telegram token",
            401: "Not authenticated",
            403: "Forbidden",
            404: "Not found",
        }.get(status_code, "Service unavailable")
        super().__init__(message)
