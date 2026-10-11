"""Offline per-run auth, financial boundaries and credential privacy."""
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import traceback

import pytest
import requests
import yaml

import degiro_to_ghostfolio as adapter
from scripts import prepare_cutover, recover_degiro
from test_degiro_sync import NOW, TARGET, configure, opening_holding, response, snapshot
from test_degiro_recovery import config, document, pending_import


ACCESS = 'SECURITY-SENTINEL'
BEARER = 'BEARER-SENTINEL'
HOST = 'http://localhost:3333'


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    for key in ('GHOST_TOKEN', 'GHOST_ACCESS_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GHOST_HOST', HOST)


@pytest.mark.parametrize('token,access', [(None, None), ('', ''), (' \t', '\n'),
    (BEARER, ACCESS)])
def test_exactly_one_nonempty_credential(monkeypatch, token, access):
    for key, value in (('GHOST_TOKEN', token), ('GHOST_ACCESS_TOKEN', access)):
        if value is not None:
            monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match='exactly one'):
        adapter.load_ghost_credentials()


@pytest.mark.parametrize('key,other', [('GHOST_TOKEN', 'GHOST_ACCESS_TOKEN'),
    ('GHOST_ACCESS_TOKEN', 'GHOST_TOKEN')])
def test_blank_other_credential_and_verbatim_value(monkeypatch, key, other):
    value = ' unicode-é ' if key == 'GHOST_ACCESS_TOKEN' else BEARER
    monkeypatch.setenv(key, value)
    monkeypatch.setenv(other, ' \t')
    credentials = adapter.load_ghost_credentials()
    assert credentials['ghost_host'] == HOST
    assert credentials['ghost_access_token' if key == 'GHOST_ACCESS_TOKEN' else 'ghost_token'] == value


def test_exchange_uses_only_approved_origin_and_no_ambient_credentials(monkeypatch, tmp_path):
    netrc = tmp_path / 'netrc'
    netrc.write_text('machine localhost login AMBIENT-SENTINEL password PASSWORD-SENTINEL\n')
    monkeypatch.setenv('NETRC', str(netrc))
    monkeypatch.setenv('HTTP_PROXY', 'http://proxy.invalid:3128')
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', '/untrusted.pem')
    calls = []
    def send(session, request, **options):
        calls.append(request.url)
        assert session.trust_env is False
        assert request.method == 'POST' and request.url == HOST + '/api/v1/auth/anonymous'
        assert json.loads(request.body) == {'accessToken': ACCESS}
        assert 'Authorization' not in request.headers
        assert options['timeout'] == (10, 30) and options['allow_redirects'] is False
        assert options['proxies'] == {} and options['verify'] is True
        return response({'authToken': BEARER}, 201)
    monkeypatch.setattr(requests.Session, 'send', send)
    assert adapter.ghost_exchange_access_token(HOST, ACCESS) == BEARER
    assert calls == [HOST + '/api/v1/auth/anonymous']


@pytest.mark.parametrize('host', ['http://public.example', HOST + '/', HOST + '?token=SECRET',
    'http://user:SECRET@localhost:3333', HOST + '/api', HOST + '#SECRET'])
def test_bad_origin_prevents_exchange(monkeypatch, host):
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: pytest.fail('HTTP attempted'))
    with pytest.raises(RuntimeError, match='origin policy'):
        adapter.ghost_exchange_access_token(host, ACCESS)


@pytest.mark.parametrize('status', [301, 302, 307, 308, 400, 401, 403, 429, 500, 503])
def test_http_failure_no_retry_or_response_disclosure(monkeypatch, caplog, status):
    calls = []
    def send(*args, **kwargs):
        calls.append(True)
        return response({'private': ACCESS + BEARER}, status)
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(RuntimeError, match=f'HTTP {status}') as error:
        adapter.ghost_exchange_access_token(HOST, ACCESS)
    assert calls == [True]
    assert ACCESS not in str(error.value) + caplog.text and BEARER not in str(error.value) + caplog.text


@pytest.mark.parametrize('error', [requests.Timeout, requests.ConnectionError, requests.exceptions.SSLError])
def test_network_failure_is_private_and_not_retried(monkeypatch, caplog, error):
    calls = []
    def send(*args, **kwargs):
        calls.append(True)
        raise error(ACCESS + BEARER)
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(RuntimeError, match='network error') as caught:
        adapter.ghost_exchange_access_token(HOST, ACCESS)
    rendered = ''.join(traceback.format_exception(caught.type, caught.value, caught.tb)) + caplog.text
    assert ACCESS not in rendered and BEARER not in rendered and calls == [True]


@pytest.mark.parametrize('body', [None, [], {'private': ACCESS}, {'authToken': None},
    {'authToken': 123}, {'authToken': ''}, {'authToken': ' '}, {'authToken': 'has space'},
    {'authToken': BEARER + '\r\nHeader: injected'}, {'authToken': BEARER + 'é'}])
def test_unusable_bearer_rejected_without_disclosure(monkeypatch, body):
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: response(body, 201))
    with pytest.raises(RuntimeError, match='no usable authToken') as error:
        adapter.ghost_exchange_access_token(HOST, ACCESS)
    assert ACCESS not in str(error.value) and BEARER not in str(error.value)


def test_invalid_json_is_private(monkeypatch):
    result = response(None, 201)
    result._content = (ACCESS + BEARER).encode()
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: result)
    with pytest.raises(RuntimeError, match='not JSON') as error:
        adapter.ghost_exchange_access_token(HOST, ACCESS)
    assert ACCESS not in str(error.value) and BEARER not in str(error.value)


@pytest.mark.parametrize('failure', [False, True])
def test_http_debug_logs_muted_and_restored(monkeypatch, caplog, failure):
    names = ('requests', 'urllib3', 'urllib3.connectionpool')
    caplog.set_level(logging.DEBUG)
    before = {name: (logging.getLogger(name).level, logging.getLogger(name).disabled,
        logging.getLogger(name).propagate) for name in names}
    def send(*args, **kwargs):
        for name in names:
            logging.getLogger(name).critical(ACCESS + BEARER)
        if failure:
            raise requests.Timeout(ACCESS)
        return response({'authToken': BEARER}, 201)
    monkeypatch.setattr(requests.Session, 'send', send)
    if failure:
        with pytest.raises(RuntimeError):
            adapter.ghost_exchange_access_token(HOST, ACCESS)
    else:
        assert adapter.ghost_exchange_access_token(HOST, ACCESS) == BEARER
    assert ACCESS not in caplog.text and BEARER not in caplog.text
    for name in names:
        logger = logging.getLogger(name)
        assert (logger.level, logger.disabled, logger.propagate) == before[name]


@pytest.mark.parametrize('mode', ['bearer', 'access'])
def test_sync_authenticates_once_before_broker_and_dry_run_reads_only(
        snapshot, monkeypatch, tmp_path, mode):
    configure(monkeypatch, tmp_path)
    if mode == 'access':
        monkeypatch.delenv('GHOST_TOKEN')
        monkeypatch.setenv('GHOST_ACCESS_TOKEN', ACCESS)
    events = []
    def send(session, request, **kwargs):
        events.append((request.method, request.path_url))
        if request.path_url == '/api/v1/auth/anonymous':
            assert request.method == 'POST'
            return response({'authToken': BEARER}, 201)
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer ' + (BEARER if mode == 'access' else 'TOKEN-SENTINEL')
        return response(TARGET if request.path_url.endswith('/target-a') else
            {'activities': [opening_holding()], 'count': 1})
    def read(*args, **kwargs):
        events.append(('BROKER', 'read'))
        snapshot['fetch_started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        snapshot['fetched_at'] = datetime.now(timezone.utc).isoformat()
        return snapshot
    monkeypatch.setattr(requests.Session, 'send', send)
    monkeypatch.setattr(adapter, 'read_degiro', read)
    result = adapter.run_sync(NOW.date(), NOW.date())
    expected = [('POST', '/api/v1/auth/anonymous')] if mode == 'access' else []
    assert events == expected + [('BROKER', 'read'), ('GET', '/api/v1/account/target-a'), ('GET', '/api/v1/activities')]
    assert result['dry_run'] is True and result['accepted'] == []


@pytest.mark.parametrize('failure', ['auth', 'mapping', 'dates', 'mode', 'target', 'source'])
def test_preflight_or_auth_failure_prevents_broker_and_financial_operations(monkeypatch, tmp_path, failure):
    path = configure(monkeypatch, tmp_path)
    monkeypatch.delenv('GHOST_TOKEN')
    monkeypatch.setenv('GHOST_ACCESS_TOKEN', ACCESS)
    if failure == 'mapping':
        path.write_text('{}')
    elif failure == 'mode':
        monkeypatch.setenv('DRY_RUN', 'invalid')
    elif failure == 'target':
        monkeypatch.setenv('GHOST_ACCOUNT_ID', '../other')
    elif failure == 'source':
        monkeypatch.setenv('DEGIRO_ACCOUNT_ID', '0')
    calls = []
    def send(session, request, **kwargs):
        calls.append((request.method, request.path_url))
        assert failure == 'auth' and request.path_url == '/api/v1/auth/anonymous'
        return response({'private': ACCESS}, 403)
    monkeypatch.setattr(requests.Session, 'send', send)
    monkeypatch.setattr(adapter, 'read_degiro', lambda *a, **kw: pytest.fail('Broker contacted'))
    with pytest.raises(RuntimeError):
        adapter.run_sync(NOW.date(), NOW.date() - timedelta(days=1) if failure == 'dates' else NOW.date())
    assert calls == ([('POST', '/api/v1/auth/anonymous')] if failure == 'auth' else [])


def test_no_refresh_after_target_rejects_new_bearer(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    monkeypatch.delenv('GHOST_TOKEN')
    monkeypatch.setenv('GHOST_ACCESS_TOKEN', ACCESS)
    monkeypatch.setattr(adapter, 'read_degiro', lambda *a, **kw: {'account_info': {'baseCurrency': 'EUR'}})
    calls = []
    def send(session, request, **kwargs):
        calls.append(request.path_url)
        return response({'authToken': BEARER}, 201) if len(calls) == 1 else response({}, 401)
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(requests.HTTPError):
        adapter.run_sync(NOW.date(), NOW.date())
    assert calls == ['/api/v1/auth/anonymous', '/api/v1/account/target-a']


@pytest.mark.parametrize('confirm', [False, True])
def test_access_recovery_preserves_confirmation_and_never_replays(config, snapshot, monkeypatch, capsys, confirm):
    intent = pending_import(config, snapshot)
    from test_degiro_sync import activity_row
    rows = [opening_holding()] + [activity_row(activity, str(index)) for index, activity in enumerate(intent['payload'].values())]
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    for key, value in {'GHOST_ACCESS_TOKEN': ACCESS, 'GHOST_ACCOUNT_ID': config['target_account'],
            'DEGIRO_ACCOUNT_ID': config['source_account'], 'STATE_DIR': config['state_dir']}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def send(session, request, **kwargs):
        calls.append((request.method, request.path_url))
        if request.path_url == '/api/v1/auth/anonymous':
            return response({'authToken': BEARER}, 201)
        assert request.method == 'GET' and request.headers['Authorization'] == 'Bearer ' + BEARER
        return response(TARGET if request.path_url.endswith('/target-a') else {'activities': rows, 'count': len(rows)})
    monkeypatch.setattr(requests.Session, 'send', send)
    args = ['--expected-intent-id', intent['id']]
    assert recover_degiro.main(args + (['--confirm-local-state'] if confirm else [])) == 0
    assert calls == [('POST', '/api/v1/auth/anonymous'), ('GET', '/api/v1/account/target-a'), ('GET', '/api/v1/activities')]
    if confirm:
        assert document(config)['pending'] is None
    else:
        assert path.read_bytes() == before
    output = capsys.readouterr()
    assert ACCESS not in output.out + output.err and BEARER not in output.out + output.err
    assert ACCESS not in path.read_text() and BEARER not in path.read_text()


def test_recovery_wrong_intent_fails_before_auth(config, snapshot, monkeypatch):
    pending_import(config, snapshot)
    credentials = {**config, 'ghost_access_token': ACCESS, 'ghost_token': None}
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: pytest.fail('HTTP attempted'))
    with pytest.raises(RuntimeError):
        adapter.readback_import_intent(credentials, expected_intent_id='f' * 32)


def test_recovery_auth_failure_retains_intent_without_reads(config, snapshot, monkeypatch):
    intent = pending_import(config, snapshot)
    path = next(Path(config['state_dir']).glob('*.yaml'))
    before = path.read_bytes()
    calls = []
    def send(session, request, **kwargs):
        calls.append(request.path_url)
        assert request.method == 'POST' and request.path_url == '/api/v1/auth/anonymous'
        return response({}, 403)
    monkeypatch.setattr(requests.Session, 'send', send)
    with pytest.raises(RuntimeError, match='HTTP 403'):
        adapter.readback_import_intent({**config, 'ghost_access_token': ACCESS, 'ghost_token': None},
            expected_intent_id=intent['id'], confirm=True)
    assert calls == ['/api/v1/auth/anonymous'] and path.read_bytes() == before


def test_capture_auth_failure_prevents_broker(monkeypatch, tmp_path):
    cfg = {'dry_run': True, 'ghost_host': HOST, 'ghost_access_token': ACCESS, 'ghost_token': None}
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: response({}, 403))
    monkeypatch.setattr(adapter, 'read_degiro', lambda *a, **kw: pytest.fail('Broker contacted'))
    with pytest.raises(RuntimeError, match='HTTP 403'):
        prepare_cutover.capture(tmp_path / 'new', cfg)


def test_auth_failure_notification_and_cli_do_not_disclose_secrets(monkeypatch, tmp_path, caplog):
    configure(monkeypatch, tmp_path, '0')
    monkeypatch.delenv('GHOST_TOKEN')
    monkeypatch.setenv('GHOST_ACCESS_TOKEN', ACCESS)
    monkeypatch.setenv('APPRISE_URLS', '["json://notify.invalid/hook"]')
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **kw: response({'secret': ACCESS + BEARER}, 403))
    monkeypatch.setattr(adapter, 'read_degiro', lambda *a, **kw: pytest.fail('Broker contacted'))
    notifications = []
    monkeypatch.setattr(adapter, 'send_notification', lambda settings, title, body: notifications.append(body) or 'sent')
    assert adapter.main(['--sync']) == 1
    assert len(notifications) == 1
    assert ACCESS not in caplog.text + notifications[0] and BEARER not in caplog.text + notifications[0]


def test_compose_accepts_both_credential_modes_from_local_or_injected_environment():
    environment = yaml.safe_load(Path('compose.yaml').read_text())['services']['degiro-sync']['environment']
    assert environment['GHOST_TOKEN'] == '${GHOST_TOKEN:-}'
    assert environment['GHOST_ACCESS_TOKEN'] == '${GHOST_ACCESS_TOKEN:-}'
