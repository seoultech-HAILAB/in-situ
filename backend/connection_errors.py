"""Actionable network errors without exposing request headers or credentials."""
import socket
import ssl


def api_connection_error(exc, purpose='LLM'):
    chain=[]; seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc)); chain.append(exc)
        exc=exc.__cause__ or exc.__context__
    if any(getattr(item,'winerror',None)==10013 or '[WinError 10013]' in str(item) for item in chain):
        return (f'{purpose} API 요청이 현재 Python 서버의 네트워크 접근 권한 제한으로 차단됐습니다 '
                '(Windows 오류 10013). 이 서버를 종료한 뒤 Windows에서 프로젝트의 '
                'run-local.cmd를 직접 실행하고 다시 시도하세요.')
    if any(isinstance(item,ssl.SSLCertVerificationError) for item in chain):
        return f'{purpose} API 서버의 TLS 인증서를 검증하지 못했습니다. Python 인증서 또는 사내 프록시 인증서 설정을 확인하세요.'
    if any(isinstance(item,socket.gaierror) for item in chain):
        return f'{purpose} API 서버 주소를 찾지 못했습니다. OPENAI_BASE_URL과 DNS 연결을 확인하세요.'
    return f'{purpose} API에 연결하지 못했습니다. OPENAI_BASE_URL과 서버의 외부 네트워크 연결을 확인하세요.'
