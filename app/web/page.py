"""The Mini App page. Self-contained: only the official Telegram Web App SDK is loaded.

The script collects device signals, hashes them with SHA-256 in the browser and
posts ``{initData, fingerprint, signals}`` to ``/api/device``. The server verifies
``initData`` (HMAC on the bot token) and answers with a verdict; the page shows it
and closes itself.
"""

VERIFY_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{bot} · проверка устройства</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font-family: -apple-system, system-ui, Roboto, sans-serif;
         background: var(--tg-theme-bg-color, #fff); color: var(--tg-theme-text-color, #111);
         display:flex; min-height:100vh; align-items:center; justify-content:center; text-align:center; }
  .card { padding: 32px 24px; max-width: 360px; }
  .icon { font-size: 56px; line-height: 1; margin-bottom: 16px; }
  h1 { font-size: 20px; margin: 0 0 8px; }
  p { margin: 0; opacity: .8; font-size: 15px; line-height: 1.4; }
  .hint { margin-top: 18px; font-size: 13px; opacity: .6; }
  .spin { display:inline-block; width:18px; height:18px; border:2px solid currentColor; border-right-color:transparent;
          border-radius:50%; animation: r .8s linear infinite; vertical-align:-3px; margin-right:8px; }
  @keyframes r { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <div class="icon" id="icon">🛡</div>
  <h1 id="title"><span class="spin"></span>Проверяем устройство…</h1>
  <p id="text">Это займёт пару секунд. Ничего нажимать не нужно.</p>
  <div class="hint" id="hint"></div>
</div>
<script>
(async function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  const $ = (id) => document.getElementById(id);
  function show(icon, title, text, hint) {
    $('icon').textContent = icon; $('title').textContent = title; $('text').textContent = text || '';
    $('hint').textContent = hint || '';
  }
  if (!tg || !tg.initData) {
    show('⚠️', 'Откройте через Telegram', 'Эта страница работает только внутри Telegram: нажмите кнопку «Подтвердить устройство» в боте.');
    return;
  }
  tg.ready(); tg.expand();

  function canvasHash() {
    try {
      const c = document.createElement('canvas'); c.width = 240; c.height = 60;
      const x = c.getContext('2d');
      x.textBaseline = 'alphabetic'; x.fillStyle = '#f60'; x.fillRect(10, 8, 90, 30);
      x.fillStyle = '#069'; x.font = '15px Arial'; x.fillText('KodoStars ✓ 🛡 fp', 4, 28);
      x.fillStyle = 'rgba(102,204,0,.7)'; x.font = '18px Times New Roman'; x.fillText('KodoStars ✓ 🛡 fp', 8, 48);
      return c.toDataURL();
    } catch (e) { return 'n/a'; }
  }
  function webgl() {
    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
      if (!gl) return 'n/a';
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      const vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
      const renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
      return vendor + ' / ' + renderer;
    } catch (e) { return 'n/a'; }
  }
  function fonts() {
    const list = ['Arial','Verdana','Times New Roman','Courier New','Georgia','Roboto','Segoe UI','Helvetica Neue','Noto Sans','Ubuntu','SF Pro Text'];
    try {
      const c = document.createElement('canvas').getContext('2d');
      const base = (font) => { c.font = '16px ' + font; return c.measureText('mmmmmmmmmmlli').width; };
      const ref = base('monospace');
      return list.filter((f) => base('"' + f + '", monospace') !== ref).join(',');
    } catch (e) { return 'n/a'; }
  }
  async function sha256(text) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  const n = navigator, s = screen;
  const signals = {
    ua: n.userAgent, platform: n.platform || '', tg_platform: tg.platform, tg_version: tg.version,
    languages: (n.languages || [n.language]).join(','),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
    screen: s.width + 'x' + s.height, dpr: String(window.devicePixelRatio || 1), color_depth: String(s.colorDepth),
    cores: String(n.hardwareConcurrency || 0), memory: String(n.deviceMemory || 0),
    touch: String(n.maxTouchPoints || 0), webgl: webgl(), canvas: '', fonts: fonts(),
  };
  signals.canvas = await sha256(canvasHash());
  const fingerprint = await sha256(Object.keys(signals).sort().map((k) => k + '=' + signals[k]).join('|'));

  try {
    const res = await fetch('/api/device', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: tg.initData, fingerprint, signals }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { throw new Error(data.error || ('HTTP ' + res.status)); }
    if (data.twink) {
      show('⚠️', 'Устройство уже использовалось', 'На этом устройстве есть другой аккаунт. Реферальные бонусы за этот аккаунт не начисляются.', 'Если это ошибка — напишите в поддержку.');
    } else {
      show('✅', 'Устройство подтверждено', 'Можно возвращаться в бота.');
      if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    }
    setTimeout(() => tg.close(), data.twink ? 4000 : 1400);
  } catch (e) {
    show('❌', 'Не удалось проверить', String(e.message || e), 'Закройте окно и попробуйте ещё раз.');
  }
})();
</script>
</body>
</html>
"""

LANDING_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{bot}</title>
<style>body{font-family:system-ui,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;background:#0d1117;color:#e6edf3}
a{color:#34d399}.c{text-align:center;padding:32px}</style></head>
<body><div class="c"><h1>⭐ {bot}</h1><p>Telegram-бот: рефералы, ежедневки, задания и Stars.</p>
<p><a href="https://t.me/{username}">Открыть бота @{username}</a></p></div></body></html>
"""
