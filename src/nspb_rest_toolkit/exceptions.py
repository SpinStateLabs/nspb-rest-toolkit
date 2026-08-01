class EPMToolkitError(Exception):
    """Base class for all nspb_rest_toolkit errors."""


class EPMConfigError(EPMToolkitError):
    """Raised for invalid or incomplete connection configuration."""


class EPMAuthError(EPMToolkitError):
    """Raised when authentication with Oracle EPM Cloud fails.

    Never includes the credential value itself in the message.
    """


class EPMHTTPError(EPMToolkitError):
    """Raised for a non-retryable or exhausted-retry HTTP failure.

    Carries the redacted response so callers can inspect status/body without
    risking credential leakage.
    """

    def __init__(self, message: str, status_code: int | None = None, redacted_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.redacted_body = redacted_body


class EPMJobError(EPMToolkitError):
    """Raised when an async job (Planning or Migration family) ends in a failed state."""


class EPMConfirmationRequiredError(EPMToolkitError):
    """Raised when a destructive operation is called without confirm=True."""
