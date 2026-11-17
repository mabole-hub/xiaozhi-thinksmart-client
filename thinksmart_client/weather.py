"""Optional weather for the office panel.

The page never sees a key or a client IP. A place name is stored only after the user saves it.
Open-Meteo is used because it needs no account and no key. With no saved place the panel stays
未接入. This file does not read the camera patch or config.py.
"""
import json
import logging
import pathlib
import re
import time

from aiohttp import ClientError, ClientTimeout

log = logging.getLogger(__name__)

PATH = pathlib.Path.home() / '.config' / 'thinksmart-client' / 'weather.json'
GEOCODE_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
CACHE_S = 600
TIMEOUT = ClientTimeout(total=8)

# WMO weather interpretation codes. Unknown codes stay numeric rather than a guessed word.
CONDITIONS = {
    0: '晴', 1: '大部晴朗', 2: '多云', 3: '阴',
    45: '雾', 48: '雾凇',
    51: '小毛毛雨', 53: '毛毛雨', 55: '浓毛毛雨',
    56: '冻毛毛雨', 57: '强冻毛毛雨',
    61: '小雨', 63: '中雨', 65: '大雨',
    66: '冻雨', 67: '强冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
    80: '小阵雨', 81: '阵雨', 82: '强阵雨',
    85: '小阵雪', 86: '阵雪',
    95: '雷暴', 96: '雷暴夹小冰雹', 99: '雷暴夹大冰雹',
}


class WeatherError(Exception):
    pass


def normalize(place):
    text = ' '.join(str(place or '').split())
    if not text:
        return ''
    if len(text) > 24 or not re.fullmatch(r'[\u4e00-\u9fffA-Za-z0-9 ·.\-]+', text):
        raise WeatherError('地名请用 24 个字以内的文字')
    return text


def read_saved():
    try:
        data = json.loads(PATH.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return None
    place = data.get('place') if isinstance(data, dict) else None
    if not isinstance(place, str) or not place:
        return None
    ident = data.get('id')
    return {'place': place, 'id': ident if isinstance(ident, int) else None}


def write_saved(place, ident):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps({'place': place, 'id': ident}, ensure_ascii=False))
    tmp.replace(PATH)


def clear_saved():
    try:
        PATH.unlink()
    except FileNotFoundError:
        pass
    _cache.clear()


_cache = {}   # (place, id) -> (monotonic, payload)


def condition(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return ''
    return CONDITIONS.get(code, f'代码 {code}')


def _locality(name, admin2):
    text = admin2 or ''
    bare = text.replace('市', '').replace('地区', '').replace('盟', '')
    if not text or bare == name or text == name:
        return ''
    return text


def _choice(row):
    name = row.get('name') or ''
    return {
        'id': row.get('id'),
        'place': name,
        'locality': _locality(name, row.get('admin2') or ''),
        'region': row.get('admin1') or '',
        'country': row.get('country') or '',
        'country_code': row.get('country_code') or '',
        'latitude': row.get('latitude'),
        'longitude': row.get('longitude'),
        'timezone': row.get('timezone') or 'auto',
        'population': row.get('population') or 0,
    }


def _listed(choice):
    return {k: choice[k] for k in ('id', 'place', 'locality', 'region', 'country')}


async def _get_json(url, params):
    from aiohttp import ClientSession
    try:
        async with ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url, params=params, headers={'Accept': 'application/json'}) as resp:
                if resp.status != 200:
                    raise WeatherError('暂时取不到')
                data = await resp.json(content_type=None)
    except WeatherError:
        raise
    except (ClientError, TimeoutError, OSError, ValueError) as e:
        log.info('weather request failed: %s', type(e).__name__)
        raise WeatherError('暂时取不到') from e
    if not isinstance(data, dict):
        raise WeatherError('暂时取不到')
    return data


async def geocode(place):
    data = await _get_json(GEOCODE_URL, {'name': place, 'count': 5, 'language': 'zh', 'format': 'json'})
    rows = [r for r in (data.get('results') or []) if isinstance(r, dict) and r.get('name') and r.get('id') is not None]
    exact = [r for r in rows if r.get('name') == place or str(r.get('name')).lower() == place.lower()]
    chosen = exact or rows
    chosen.sort(key=lambda r: r.get('population') or 0, reverse=True)
    return [_choice(r) for r in chosen[:5]]


def _public(choice, current):
    temp = current.get('temperature_2m')
    if not isinstance(temp, (int, float)):
        raise WeatherError('暂时取不到')
    return {
        'configured': True,
        'ok': True,
        'query': choice.get('query') or choice['place'],
        'id': choice['id'],
        'place': choice['place'],
        'region': choice['region'],
        'country': choice['country'],
        'country_code': choice['country_code'],
        'temperature': temp,
        'condition': condition(current.get('weather_code')),
        'observed_at': current.get('time') or '',
        'timezone': choice.get('timezone') or '',
        'source': 'open-meteo',
    }


async def observe(choice):
    if choice.get('latitude') is None or choice.get('longitude') is None:
        raise WeatherError('暂时取不到')
    data = await _get_json(FORECAST_URL, {
        'latitude': choice['latitude'],
        'longitude': choice['longitude'],
        'current': 'temperature_2m,weather_code',
        'timezone': choice.get('timezone') or 'auto',
    })
    current = data.get('current') or {}
    if not isinstance(current, dict):
        raise WeatherError('暂时取不到')
    return _public(choice, current)


async def _resolve(place, ident):
    choices = await geocode(place)
    if ident is not None:
        match = [c for c in choices if c['id'] == ident]
        if not match:
            raise WeatherError('请重新选择地点')
        return match
    return choices


async def status():
    saved = read_saved()
    if not saved:
        return {'configured': False}
    key = (saved['place'], saved['id'])
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        choices = await _resolve(saved['place'], saved['id'])
        if len(choices) != 1:
            return {'configured': True, 'ok': False, 'query': saved['place'], 'error': '地点有多处，请重新选择',
                    'choose': [_listed(c) for c in choices]}
        payload = await observe(dict(choices[0], query=saved['place']))
    except WeatherError as e:
        if hit:
            return hit[1]
        return {'configured': True, 'ok': False, 'query': saved['place'], 'error': str(e)}
    _cache[key] = (time.monotonic(), payload)
    return payload


async def save_place(place, ident=None):
    place = normalize(place)
    if not place:
        clear_saved()
        return {'configured': False}
    choices = await _resolve(place, ident)
    if ident is None and len(choices) > 1:
        return {'configured': False, 'ok': False, 'query': place,
                'choose': [_listed(c) for c in choices]}
    payload = await observe(dict(choices[0], query=place))
    write_saved(place, payload['id'])
    _cache[(place, payload['id'])] = (time.monotonic(), payload)
    return payload


async def handle_get(_request):
    return _json(await status())


async def handle_post(request):
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    ident = body.get('id')
    if ident is not None and not isinstance(ident, int):
        return _json({'ok': False, 'error': '请重新选择地点'}, status=400)
    try:
        return _json(await save_place(body.get('place'), ident))
    except WeatherError as e:
        return _json({'ok': False, 'configured': bool(read_saved()), 'error': str(e)}, status=400)


def _json(data, status=200):
    from aiohttp import web
    return web.json_response(data, status=status)
