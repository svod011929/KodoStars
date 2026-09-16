from aiogram.fsm.state import State, StatesGroup


class UserFSM(StatesGroup):
    promo_code = State()
