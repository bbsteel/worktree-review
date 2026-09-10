"""GitHub adapter configuration and transport errors."""


class ServerConfigurationError(RuntimeError):
    """Required production server configuration is absent or invalid."""


class GitHubApiError(RuntimeError):
    """The trusted GitHub API could not resolve a retry input."""
