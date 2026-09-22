from aiogram.fsm.state import State, StatesGroup


class AdminFSM(StatesGroup):
    # users
    user_search = State()
    user_adjust = State()
    user_note = State()
    user_message = State()
    user_ban_reason = State()
    # withdrawals
    wd_reject_reason = State()
    # broadcast
    bc_message = State()
    bc_button = State()
    # catalog: tasks
    task_title = State()
    task_desc = State()
    task_reward = State()
    task_target = State()
    task_edit = State()
    # catalog: boosts
    boost_title = State()
    boost_desc = State()
    boost_price = State()
    boost_param = State()
    boost_edit = State()
    # promo
    promo_code = State()
    promo_reward = State()
    promo_limit = State()
    promo_days = State()
    # settings & access
    setting_value = State()
    channel_add = State()
    channel_link = State()
    admin_add = State()
    # data
    import_users = State()

    amb_l1_bonus = State()
    amb_l1_percent = State()
    amb_l2_bonus = State()
    amb_l2_percent = State()
    amb_promo_reward = State()
    amb_promo_max_uses = State()
    amb_reject_reason = State()
    amb_chat_id = State()
