class WebhookManagerError(Exception):
    pass


class NotFoundError(WebhookManagerError):
    pass


class ConflictError(WebhookManagerError):
    pass


class ForbiddenError(WebhookManagerError):
    pass


class RateLimitError(WebhookManagerError):
    pass

