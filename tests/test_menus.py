"""Menu structure: compact hubs for admin, grouped user main menu."""

from app.bot import keyboards as user_kb
from app.bot.admin import keyboards as admin_kb
from app.bot.admin import texts as admin_texts
from app.config import Settings


def _callbacks(markup) -> set[str]:
    out: set[str] = set()
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                out.add(btn.callback_data)
    return out


def test_user_main_menu_is_compact_and_grouped() -> None:
    markup = user_kb.main_menu(is_admin=False)
    assert len(markup.inline_keyboard) <= 5
    data = _callbacks(markup)
    assert {"menu:daily", "menu:tasks", "menu:profile", "menu:refs", "menu:withdraw", "menu:amb"} <= data
    assert "admin:home" not in data

    admin_menu = user_kb.main_menu(is_admin=True)
    assert "admin:home" in _callbacks(admin_menu)


def test_main_menu_puts_ref_payout_first() -> None:
    markup = user_kb.main_menu(l1_bonus=10)
    first = markup.inline_keyboard[0][0]
    assert first.text == "10 за друга"
    assert first.callback_data == "menu:refs"
    assert len(markup.inline_keyboard) <= 5


def test_admin_home_uses_hubs_not_flat_list() -> None:
    markup = admin_kb.home(pending=3, amb_pending=2)
    data = _callbacks(markup)
    assert "admin:catalog" in data and "admin:system" in data
    assert "admin:amb" in data
    assert "admin:tasks" not in data  # moved under catalog hub
    assert "admin:pay:0" not in data  # moved under system hub
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any(t == "Выводы (3)" for t in labels)
    assert any(t == "Амбассадоры (2)" for t in labels)
    assert len(markup.inline_keyboard) <= 5


def test_catalog_and_system_hubs() -> None:
    catalog = _callbacks(admin_kb.catalog_hub())
    assert {"admin:tasks", "admin:boosts", "admin:promo:list:0", "admin:home"} <= catalog

    system = _callbacks(admin_kb.system_hub())
    assert {"admin:pay:0", "admin:adm", "admin:audit:0", "admin:fraud:0", "admin:data", "admin:home"} <= system


def test_provider_screen_lists_full_webhook_urls() -> None:
    shown = admin_texts.providers_home({}, {}, Settings(web_public_url="https://mini.example"))
    for path in (
        "/api/piarflow/webhook",
        "/api/tgrass/unsubscribe",
        "/api/tgrass/webhook",
        "/api/tgrass/member",
    ):
        assert f"https://mini.example{path}" in shown
    bare = admin_texts.providers_home({}, {}, Settings(web_public_url=""))
    assert "WEB_PUBLIC_URL не задан" in bare
    assert "/api/piarflow/webhook" in bare
