"""Office landscape page: keep the v2 button and SSE contract, and do not invent live data.

Static checks only. They do not open a device, a camera, or the network.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / 'web' / 'v2' / 'index.html').read_text()
CSS = (ROOT / 'web' / 'v2' / 'app.css').read_text()
JS = (ROOT / 'web' / 'v2' / 'app.js').read_text()

REQUIRED_IDS = [
    'time', 'bigTime', 'bigDate', 'greet', 'title', 'hint', 'btnAbort', 'btnMic', 'micRing', 'btnEnd',
    'reportText', 'link', 'pillLogo', 'pillLabel', 'pillModel', 'grid', 'sleepSwitch', 'sleepTimes',
    'sleepStart', 'sleepEnd', 'sleepNote', 'brightRange', 'brightNum', 'brightNote', 'offSwitch',
    'offMinutes', 'offNote', 'upd', 'gearDot', 'updTitle', 'updSub', 'updNotes', 'updBtn', 'updBar',
    'updFill', 'clearBtn', 'clearMemBtn', 'ipNum', 'ipSub', 'btnSettings', 'settings', 'settingsClose',
    'reportPill', 'headLogo', 'headTitle', 'headMeta', 'messages', 'toast', 'hud', 'hudFill', 'hudNum',
    'sheet', 'sheetClose', 'modelPill', 'chips', 'verPill', 'btnVision', 'btnMusic',
    'cardWeather', 'cardAgenda', 'cardAlbum',
]


def _attr(id_, name):
    tag = re.search(r'<[^>]*\bid="%s"[^>]*>' % id_, HTML)
    assert tag, id_
    return name in tag.group(0)


def test_required_controls_stay():
    for id_ in REQUIRED_IDS:
        assert f'id="{id_}"' in HTML


def test_disabled_web_search_button_is_gone():
    assert 'id="btnSearch"' not in HTML
    assert 'class="action search"' not in HTML
    assert '联网搜索' not in HTML
    for id_ in ('btnMic', 'btnVision', 'btnMusic'):
        assert f'id="{id_}"' in HTML


def test_unwired_panels_are_disabled_and_say_so():
    assert 'id="weatherValue">未接入' in HTML
    assert '不用本机位置' in HTML
    assert _attr('cardAgenda', 'disabled')
    assert _attr('cardAlbum', 'disabled') and '无照片' in HTML
    assert '播放一首本地歌曲' in JS
    assert '不会拍照' in JS
    assert 'navigator.geolocation' not in JS
    assert 'open-meteo' not in JS
    for absent in ('微信', '电话', 'tel:', 'weixin', 'wechat'):
        assert absent not in HTML.lower()


def test_no_external_assets_or_canvas_runtime():
    css_rules = re.sub(r'/\*.*?\*/', '', CSS, flags=re.S)
    for text in (HTML, CSS, JS):
        assert 'grok/canvas' not in text
        assert '@import' not in text
        assert 'fonts.googleapis' not in text
        assert 'fonts.gstatic' not in text
    assert 'backdrop-filter' not in css_rules


def test_event_and_button_contract():
    assert "new EventSource('/events')" in JS
    for path in ('/api/wake', '/api/ptt/start', '/api/ptt/stop', '/api/abort', '/api/end',
                 '/api/text', '/api/model', '/api/sleep', '/api/brightness', '/api/screen-off',
                 '/api/reports/play', '/api/history/clear', '/api/network', '/api/update/check',
                 '/api/update/install'):
        assert path in JS
    assert 'function welcomeShown(' in JS
    assert "data-m=\"10\"" in HTML


def test_default_page_is_not_a_fixture():
    assert 'class="demo"' not in HTML
    assert '【测试】' not in HTML
    assert "params.get('shot')" in JS
    assert '测试数据，未连接实体机' in HTML


def test_motion_can_be_reduced():
    assert 'prefers-reduced-motion' in CSS
    assert '.still *' in CSS
