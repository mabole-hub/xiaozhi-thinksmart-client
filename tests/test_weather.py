"""Weather proxy: no place means 未接入, a place is explicit, and numbers come from the provider.

The live check talks to Open-Meteo only when the network allows it. It does not use a key or an IP.
"""
import asyncio

import pytest
from aiohttp import web

from thinksmart_client import weather


@pytest.fixture
def place_file(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, 'PATH', tmp_path / 'weather.json')
    weather._cache.clear()
    yield
    weather._cache.clear()


def test_blank_place_is_not_configured(place_file):
    assert asyncio.run(weather.status()) == {'configured': False}


def test_bad_place_is_rejected(place_file):
    with pytest.raises(weather.WeatherError):
        weather.normalize('https://evil.example/x')
    with pytest.raises(weather.WeatherError):
        weather.normalize('大庆' * 20)


def test_two_matches_wait_for_a_choice(place_file, monkeypatch):
    calls = []

    async def fake(url, params):
        calls.append(url)
        if 'search' in url:
            return {'results': [
                {'id': 2, 'name': '大庆', 'latitude': 22.0, 'longitude': 110.0, 'country_code': 'CN',
                 'country': '中国', 'admin1': '广东', 'admin2': '茂名市', 'timezone': 'Asia/Shanghai', 'population': 10},
                {'id': 1, 'name': '大庆', 'latitude': 46.5, 'longitude': 125.0, 'country_code': 'CN',
                 'country': '中国', 'admin1': '黑龙江', 'admin2': '大庆市', 'timezone': 'Asia/Shanghai', 'population': 100},
            ]}
        raise AssertionError('forecast before a choice')

    monkeypatch.setattr(weather, '_get_json', fake)
    got = asyncio.run(weather.save_place('大庆'))
    assert got['configured'] is False
    assert [c['region'] for c in got['choose']] == ['黑龙江', '广东']
    assert got['choose'][0]['locality'] == ''
    assert got['choose'][1]['locality'] == '茂名市'
    assert 'temperature' not in got
    assert not weather.PATH.exists()
    assert calls == [weather.GEOCODE_URL]


def test_chosen_place_stores_the_reading_and_a_failure_does_not_invent_one(place_file, monkeypatch):
    async def fake(url, params):
        if 'search' in url:
            return {'results': [
                {'id': 1, 'name': '大庆', 'latitude': 46.5, 'longitude': 125.0, 'country_code': 'CN',
                 'country': '中国', 'admin1': '黑龙江', 'timezone': 'Asia/Shanghai', 'population': 100},
            ]}
        assert params['latitude'] == 46.5
        return {'current': {'temperature_2m': -2.5, 'weather_code': 0, 'time': '2026-11-17T12:00'}}

    monkeypatch.setattr(weather, '_get_json', fake)
    saved = asyncio.run(weather.save_place('大庆'))
    assert saved['ok'] is True
    assert saved['temperature'] == -2.5
    assert saved['condition'] == '晴'
    assert saved['region'] == '黑龙江'
    assert weather.read_saved() == {'place': '大庆', 'id': 1}

    weather._cache.clear()

    async def down(url, params):
        raise weather.WeatherError('暂时取不到')

    monkeypatch.setattr(weather, '_get_json', down)
    missed = asyncio.run(weather.status())
    assert missed['configured'] is True and missed['ok'] is False
    assert 'temperature' not in missed

    cleared = asyncio.run(weather.save_place(''))
    assert cleared == {'configured': False}
    assert asyncio.run(weather.status()) == {'configured': False}


def test_http_get_stays_unconfigured(place_file):
    async def run():
        from aiohttp.test_utils import TestClient, TestServer
        app = web.Application()
        app.router.add_get('/api/weather', weather.handle_get)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            body = await (await client.get('/api/weather')).json()
        finally:
            await client.close()
        assert body == {'configured': False}

    asyncio.run(run())


def test_page_route_is_optional_and_present():
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent / 'thinksmart_client' / 'web.py').read_text()
    assert 'weather.handle_get' in source and 'weather.handle_post' in source
    assert 'request.remote' not in source


def test_unknown_code_is_not_a_guessed_word():
    assert weather.condition(1234) == '代码 1234'


@pytest.mark.asyncio
async def test_live_daqing_when_network_allows():
    try:
        choices = await weather.geocode('大庆')
    except weather.WeatherError:
        pytest.skip('open-meteo unreachable')
    match = next((c for c in choices if c['region'] == '黑龙江'), None)
    if match is None:
        pytest.skip('geocoder did not return 黑龙江')
    try:
        data = await weather.observe(dict(match, query='大庆'))
    except weather.WeatherError:
        pytest.skip('forecast unreachable')
    assert data['place']
    assert data['region'] == '黑龙江'
    assert isinstance(data['temperature'], (int, float))
    assert data['source'] == 'open-meteo'
