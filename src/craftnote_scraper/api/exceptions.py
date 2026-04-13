class CraftnoteAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CraftnoteAuthenticationError(CraftnoteAPIError):
    pass


class CraftnoteNotFoundError(CraftnoteAPIError):
    pass


class CraftnoteRateLimitError(CraftnoteAPIError):
    pass
