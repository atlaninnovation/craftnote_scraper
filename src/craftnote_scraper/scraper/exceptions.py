class ScraperError(Exception):
    pass


class LoginError(ScraperError):
    pass


class SessionExpiredError(ScraperError):
    pass


class TwoFactorRequiredError(ScraperError):
    pass


class RateLimitedError(ScraperError):
    pass


class DownloadError(ScraperError):
    pass


class ChatNavigationError(ScraperError):
    pass


class FileNotFoundInChatError(ScraperError):
    pass
