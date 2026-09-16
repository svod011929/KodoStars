class EconomyError(Exception):
    """Base class for user-facing domain errors (``message`` is safe to show)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InsufficientFunds(EconomyError):
    pass


class CooldownActive(EconomyError):
    pass


class AlreadyClaimed(EconomyError):
    pass


class UserBanned(EconomyError):
    pass


class WithdrawalError(EconomyError):
    pass


class PromoError(EconomyError):
    pass


class NotFound(EconomyError):
    pass


class ValidationError(EconomyError):
    pass


class AccessDenied(EconomyError):
    pass
