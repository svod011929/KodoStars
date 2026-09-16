from aiogram.fsm.state import State, StatesGroup


class UserFSM(StatesGroup):
    withdraw_amount = State()
    promo_code = State()
