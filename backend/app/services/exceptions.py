class ServiceError(Exception):
    """Base class for service-layer errors."""


class NotFoundError(ServiceError):
    """Raised when a requested resource or lookup result is not found."""


class UpstreamUnavailableError(ServiceError):
    """Raised when an external provider, dataset, or internal source is unavailable."""


class BadRequestError(ServiceError):
    """Raised when the service receives malformed or unsupported input."""


class UnauthorizedError(ServiceError):
    """Raised when authentication is required or invalid."""


class ForbiddenError(ServiceError):
    """Raised when the caller is authenticated but not allowed to perform the action."""