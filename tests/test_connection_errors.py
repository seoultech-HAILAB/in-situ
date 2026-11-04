import socket
import ssl
import httpx
from backend.connection_errors import api_connection_error


def test_permission_error_has_an_actionable_message_for_both_llm_paths():
    denied=PermissionError(13,'socket denied');denied.winerror=10013
    outer=httpx.ConnectError('connection failed');outer.__cause__=denied
    for purpose in ('LLM','자연어 설명'):
        message=api_connection_error(outer,purpose)
        assert purpose in message and '10013' in message and 'run-local.cmd' in message


def test_certificate_failures_keep_certificate_verification_enabled():
    assert 'TLS' in api_connection_error(ssl.SSLCertVerificationError('certificate failed'))


def test_dns_failure_names_the_configuration_field_without_disclosing_the_url():
    message=api_connection_error(socket.gaierror(-1,'lookup failed'))
    assert 'OPENAI_BASE_URL' in message and 'DNS' in message


def test_exception_contents_cannot_leak_a_key_into_the_user_message():
    exc=httpx.ConnectError('Bearer sk-private-key https://private.example/?token=private')
    message=api_connection_error(exc)
    assert 'private' not in message and 'sk-' not in message
