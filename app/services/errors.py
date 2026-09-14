class EconomyError(Exception):
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
