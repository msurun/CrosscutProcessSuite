"""Exercise PI reads with synthetic recorded responses.

No test requires credentials or access to a plant historian.
"""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from crosscut_connectors.base import SourceConnectionError
from crosscut_connectors.piwebapi_connector import PiWebApiConnector
from crosscut_connectors.registry import connector_from_source

FIXTURES = Path(__file__).parent / 'fixtures' / 'piwebapi'
BASE_URL = 'https://synthetic.invalid/piwebapi'
START = '2026-01-01T00:00:00Z'
END = '2026-01-01T00:00:02Z'


class RecordedTransport:
    """Replay fixture pages while retaining requests for protocol assertions."""

    def __init__(self, *names: str) -> None:
        self.responses = [json.loads((FIXTURES / f'{name}.json').read_text()) for name in names]
        self.requests = []

    def __call__(self, request, timeout):
        """Return the next response and record the exact GET request."""
        self.requests.append(request)
        assert request.get_method() == 'GET'
        return self.responses.pop(0)


def test_browse_lists_servers_and_filtered_points():
    """Browse exposes server folders and synthetic point WebIds."""
    transport = RecordedTransport('servers', 'points')
    connector = PiWebApiConnector(BASE_URL, {'name_filter': 'SYN.*'}, transport)
    assert connector.browse()[0].id == 'server'
    assert connector.browse('server')[0].id == 'temperature'
    assert parse_qs(urlsplit(transport.requests[1].full_url).query)['nameFilter'] == ['SYN.*']


def test_metadata_converts_zero_and_span_to_limits():
    """PI span adds to zero rather than being the upper limit."""
    connector = PiWebApiConnector(BASE_URL, transport=RecordedTransport('point'))
    metadata = connector.metadata(['temperature'])[0]
    assert (metadata.unit, metadata.eng_min, metadata.eng_max) == ('degC', -20, 180)


def test_recorded_history_continues_at_last_timestamp_without_duplicate():
    """Inclusive boundary replay contributes only one copy of the boundary event."""
    transport = RecordedTransport('recorded1', 'recorded2', 'recorded3')
    connector = PiWebApiConnector(BASE_URL, {'max_count': 2}, transport)
    history = connector.history(['temperature'], START, END)
    assert [sample['value'] for sample in history['temperature']] == [10, 11, 12]
    query = parse_qs(urlsplit(transport.requests[1].full_url).query)
    assert query['startTime'] == ['2026-01-01T00:00:01Z']
    assert query['maxCount'] == ['2']


def test_batch_snapshot_marks_system_digital_state_bad_with_reason():
    """System digital states never become numerical process measurements."""
    transport = RecordedTransport('live')
    snapshot = PiWebApiConnector(BASE_URL, transport=transport).read_snapshot(
        ['temperature', 'pressure', 'flow', 'level'])
    assert snapshot.comm_ok
    assert snapshot.values['pressure'].value is None
    assert snapshot.values['pressure'].quality == 2
    assert snapshot.values['temperature'].quality == 0
    assert snapshot.values['flow'].quality == 1
    assert snapshot.values['level'].quality == 1
    assert 'Bad Input' in snapshot.reason
    assert parse_qs(urlsplit(transport.requests[0].full_url).query)['webId'] == [
        'temperature', 'pressure', 'flow', 'level']


def unauthorized(request, timeout):
    """Simulate an authentication rejection without contacting a server."""
    raise HTTPError(request.full_url, 401, 'Unauthorized', {}, None)


def timed_out(request, timeout):
    """Simulate a network timeout."""
    raise TimeoutError('synthetic timeout')


def test_http_401_explains_authentication_failure():
    """Explicit reads surface a clear authentication error."""
    connector = PiWebApiConnector(BASE_URL, transport=unauthorized)
    with pytest.raises(SourceConnectionError, match='401.*authentication'):
        connector.browse()


def test_timeout_explains_connection_failure():
    """Explicit reads surface a clear timeout error."""
    connector = PiWebApiConnector(BASE_URL, transport=timed_out)
    with pytest.raises(SourceConnectionError, match='timeout'):
        connector.read_live(['temperature'])


def test_snapshot_timeout_marks_all_tags_bad():
    """Control cycle callers receive a failed snapshot on communication loss."""
    snapshot = PiWebApiConnector(BASE_URL, transport=timed_out).read_snapshot(['temperature'])
    assert not snapshot.comm_ok
    assert snapshot.values['temperature'].quality == 2
    assert 'timeout' in snapshot.reason


def test_interpolated_history_uses_seconds_interval():
    """A requested sampling period selects the PI interpolated endpoint."""
    transport = RecordedTransport('recorded1')
    connector = PiWebApiConnector(BASE_URL, transport=transport)
    assert len(connector.history(['temperature'], START, END, 1)['temperature']) == 2
    assert '/interpolated?' in transport.requests[0].full_url
    assert parse_qs(urlsplit(transport.requests[0].full_url).query)['interval'] == ['1s']


def test_registry_accepts_source_level_pi_configuration():
    """The factory carries source fields into the PI adapter."""
    connector = connector_from_source({'driver': 'pi', 'base_url': BASE_URL, 'web_id': 'server'})
    assert isinstance(connector, PiWebApiConnector)
    assert connector.options['web_id'] == 'server'


def test_bearer_credentials_are_resolved_from_environment(monkeypatch):
    """Site configuration names an environment variable rather than a secret."""
    monkeypatch.setenv('SYNTHETIC_PI_TOKEN', 'synthetic-token')
    transport = RecordedTransport('servers')
    connector = PiWebApiConnector(BASE_URL, {'auth': {
        'kind': 'bearer', 'credential_env': 'SYNTHETIC_PI_TOKEN'}}, transport)
    connector.browse()
    assert transport.requests[0].get_header('Authorization') == 'Bearer synthetic-token'

@pytest.mark.parametrize('state', ['Bad Input', 'I/O Timeout', 'Shutdown'])
def test_system_digital_state_names_are_preserved(state):
    """PI system states remain bad even when a response incorrectly marks them good."""
    from crosscut_connectors.piwebapi_connector import _history_sample

    sample = _history_sample({'Timestamp': START, 'Good': True,
                              'Value': {'Name': state, 'IsSystem': True}})
    assert sample['quality'] == 2
    assert sample['value'] is None
    assert sample['reason'] == state


def test_bad_good_flag_overrides_questionable():
    """Uncertain flags cannot promote a bad value to usable quality."""
    from crosscut_connectors.piwebapi_connector import _live_value

    value = _live_value({'Value': 10, 'Good': False, 'Questionable': True})
    assert value.quality == 2


def test_stalled_recorded_paging_raises_instead_of_looping():
    """A repeated full boundary page signals an incomplete history read."""
    transport = RecordedTransport('recorded1', 'recorded1')
    connector = PiWebApiConnector(BASE_URL, {'max_count': 2}, transport)
    with pytest.raises(SourceConnectionError, match='stalled'):
        connector.history(['temperature'], START, END)


def test_basic_auth_uses_an_environment_reference(monkeypatch):
    """Basic authorization encodes runtime credentials, never site literals."""
    monkeypatch.setenv('SYNTHETIC_PI_BASIC', 'reader:synthetic')
    transport = RecordedTransport('servers')
    connector = PiWebApiConnector(BASE_URL, {'auth': {
        'kind': 'basic', 'credential_env': 'SYNTHETIC_PI_BASIC'}}, transport)
    connector.browse()
    assert transport.requests[0].get_header('Authorization') == 'Basic cmVhZGVyOnN5bnRoZXRpYw=='


def test_missing_credentials_explain_how_to_configure_environment(monkeypatch):
    """Missing credentials fail without disclosing any credential values."""
    monkeypatch.delenv('SYNTHETIC_PI_MISSING', raising=False)
    connector = PiWebApiConnector(BASE_URL, {'auth': {
        'kind': 'bearer', 'credential_env': 'SYNTHETIC_PI_MISSING'}})
    with pytest.raises(SourceConnectionError, match='environment variable'):
        connector.browse()


def test_kerberos_uses_an_injected_negotiate_transport():
    """Negotiate transports receive ordinary GET requests for the service identity."""
    connector = PiWebApiConnector(BASE_URL, {'auth': {'kind': 'kerberos'}},
                                  RecordedTransport('servers'))
    assert connector.browse()[0].id == 'server'


def test_source_schema_rejects_inline_auth_password():
    """The auth schema permits environment references but forbids literal secrets."""
    from jsonschema import Draft202012Validator

    schema = json.loads((Path(__file__).parents[2] / 'schemas/site.schema.json').read_text())
    auth_schema = schema['$defs']['source']['properties']['auth']
    assert list(Draft202012Validator(auth_schema).iter_errors(
        {'kind': 'basic', 'credential_env': 'PI_BASIC', 'password': 'synthetic'}))
    assert not list(Draft202012Validator(auth_schema).iter_errors(
        {'kind': 'basic', 'credential_env': 'PI_BASIC'}))
