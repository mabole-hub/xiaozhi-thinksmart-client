"""Weather icons follow Open-Meteo WMO codes. Unknown data is not drawn as sun."""
import json
import re
import subprocess
from pathlib import Path

from thinksmart_client.weather import CONDITIONS

JS = (Path(__file__).resolve().parent.parent / 'web' / 'v2' / 'app.js').read_text()
CHUNK = JS[JS.index('const WMO_KIND'):JS.index('function weatherGlyph')] + JS[JS.index('function weatherGlyph'):JS.index('function formatTemp')]


def _node(expr):
    out = subprocess.run(['node', '-e', CHUNK + expr], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_every_server_code_has_the_same_icon_as_its_label():
    for code, label in CONDITIONS.items():
        assert _node(f'console.log(JSON.stringify(weatherKind({code}, "")))') == _node(
            f'console.log(JSON.stringify(weatherKind(null, {json.dumps(label)})))')
        assert _node(f'console.log(JSON.stringify(weatherKind({code}, "")))') in {
            'sun', 'cloud', 'fog', 'rain', 'snow', 'thunder'}


def test_clear_cloud_fog_rain_snow_thunder_are_distinct():
    expect = {0: 'sun', 1: 'sun', 2: 'cloud', 3: 'cloud', 45: 'fog', 61: 'rain', 71: 'snow', 95: 'thunder'}
    for code, kind in expect.items():
        assert _node(f'console.log(JSON.stringify(weatherKind({code}, "晴")))') == kind


def test_unknown_code_is_not_sun_even_if_the_words_say_clear():
    assert _node('console.log(JSON.stringify(weatherKind(1234, "晴")))') == 'unknown'
    assert _node('console.log(JSON.stringify(weatherKind(null, "")))') == 'unknown'
    assert _node('console.log(JSON.stringify(weatherKind(null, "代码 7")))') == 'unknown'
    unknown = _node('console.log(JSON.stringify(weatherGlyph("unknown")))')
    sun = _node('console.log(JSON.stringify(weatherGlyph("sun")))')
    assert 'data-kind=\\"unknown\\"' in unknown or 'data-kind="unknown"' in unknown
    assert 'M24 3v7' not in unknown
    assert 'M24 3v7' in sun
