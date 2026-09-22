from aiogram.fsm.state import State, StatesGroup


class UserFSM(StatesGroup):
    promo_code = State()
    amb_link = State()
    amb_title = State()
