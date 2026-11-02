"""Optional access boundary for a trusted-team pilot, disabled for local development."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import threading
from contextvars import ContextVar
from collections import OrderedDict, deque
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

LOCAL_ORIGINS = {'http://127.0.0.1:8000', 'http://localhost:8000', 'http://127.0.0.1:5173', 'http://localhost:5173'}
COOKIE = 'trace_team'
request_identity = ContextVar('trace_request_identity',default=None)
_attempts = OrderedDict()
_attempt_lock = threading.Lock()


def allow_attempt(request):
    """Bound password work; authenticated cookie requests do not consume attempts."""
    key = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    with _attempt_lock:
        recent = _attempts.setdefault(key,deque())
        _attempts.move_to_end(key)
        while recent and recent[0] <= now-60:
            recent.popleft()
        if len(recent)>=30:
            return False
        recent.append(now)
        while len(_attempts)>2048:
            _attempts.popitem(last=False)
    return True


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def check_password(password, stored):
    try:
        return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


def config():
    # Account login is retired for the shared development prototype. Historical
    # access tests/records may opt in explicitly; an old access file alone must
    # never bring back the login screen on a copied installation.
    if os.getenv('TRACE_LEGACY_AUTH') != '1':
        return None
    name = os.getenv('TRACE_ACCESS_FILE')
    if not name:
        return None
    # A missing or invalid configured file fails closed (including after rotation).
    data = json.loads(Path(name).read_text(encoding='utf-8-sig'))
    if len(data.get('signing_key', '')) < 32 or not data.get('users'):
        raise ValueError('팀 접속 설정이 올바르지 않습니다.')
    return data


def origins(cfg=None):
    return LOCAL_ORIGINS | set((cfg or {}).get('allowed_origins', []))


def token_for(name, user, cfg):
    body = base64.urlsafe_b64encode(json.dumps({'name':name, 'expires':int(time.time())+43200,
        'credential':hashlib.sha256(user['password_hash'].encode()).hexdigest()}).encode()).decode()
    return body + '.' + hmac.new(cfg['signing_key'].encode(), body.encode(), hashlib.sha256).hexdigest()


def principal(request, cfg):
    cookie = request.cookies.get(COOKIE, '')
    try:
        body, signature = cookie.rsplit('.', 1)
        expected = hmac.new(cfg['signing_key'].encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body))
        user = cfg['users'][payload['name']]
        if payload['expires'] <= time.time() or payload['credential'] != hashlib.sha256(user['password_hash'].encode()).hexdigest():
            raise ValueError()
        return identity_for(payload['name'],user)
    except (ValueError, KeyError, TypeError):
        pass
    try:
        scheme, value = request.headers.get('authorization', '').split(' ', 1)
        if scheme.lower() != 'basic':
            return None
        name, password = base64.b64decode(value, validate=True).decode().split(':', 1)
        if not allow_attempt(request):
            request.state.auth_throttled = True
            return None
        user = cfg['users'].get(name)
        if user and check_password(password, user['password_hash']):
            return identity_for(name,user)
    except (ValueError, TypeError, UnicodeError):
        pass
    return None


def identity_for(name,user):
    return {'name':name,'role':user['role'],'participant_id':user.get('participant_id',name if user['role']=='participant' else None),
            'pilot':user.get('pilot') is True}


def safe_next(value):
    return value if len(value)<2048 and (value=='/' or value.startswith('/?')) and not any(ord(c)<32 for c in value) else ''


def login_page(failed=False, next_url=''):
    return HTMLResponse('''<!doctype html><html lang="ko"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TRACE · 팀 접속</title><style>body{margin:0;background:#f5f6f8;color:#203044;font:16px system-ui;display:grid;min-height:100vh;place-items:center}main{background:white;border:1px solid #dce2e8;border-radius:16px;padding:36px;width:min(360px,78vw)}h1{font-size:26px;margin:0 0 10px}p{color:#657489;line-height:1.6;font-size:14px}label{display:block;margin:20px 0 8px;font-size:14px}input,button{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;border:1px solid #c9d1db;font:inherit}button{margin-top:24px;background:#2768d9;color:white;border:0;cursor:pointer}.error{color:#b93632}</style>
<main><h1>TRACE <small>팀 파일럿</small></h1><p>테이블 변환 검수와 과제 후보를 시험하는 공간입니다.<br>공유받은 접속 정보를 입력하세요.</p>'''
        + ('<p class="error">접속 정보를 확인해 주세요.</p>' if failed else '') + '''
<form method="post" action="/auth/login"><input type="hidden" name="next" value="''' + escape(safe_next(next_url),quote=True) + '''"><label for="username">접속 이름</label><input id="username" name="username" autocomplete="username" placeholder="예: P01" required maxlength="80"><label for="password">비밀번호</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="200"><button>접속하기</button></form></main></html>''', status_code=401 if failed else 200)


async def gate(request):
    """Return a response when handled/denied, otherwise attach the verified role."""
    try:
        cfg = config()
    except (OSError, ValueError, TypeError):
        return JSONResponse({'detail':'팀 접속 설정을 확인해야 합니다.'}, status_code=503)
    request.state.access_config = cfg
    request.state.access_role = 'local'
    request.state.access_identity = None
    if not cfg:
        return None
    origin = request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in origins(cfg):
        return Response('허용되지 않은 출처입니다.', status_code=403)
    route = request.url.path
    if route == '/login' and request.method == 'GET':
        return login_page(next_url=request.query_params.get('next',''))
    if route == '/auth/login' and request.method == 'POST':
        if not allow_attempt(request):
            return JSONResponse({'detail':'접속 시도가 많습니다. 잠시 후 다시 시도해 주세요.'},status_code=429,headers={'Retry-After':'60'})
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>2000:
                return Response('로그인 요청이 너무 큽니다.',status_code=413)
            raw.extend(chunk)
        try:
            fields = parse_qs(raw.decode())
            name, password = fields.get('username',[''])[0], fields.get('password',[''])[0]
            user = cfg['users'].get(name)
            if not user or not check_password(password, user['password_hash']):
                return login_page(True)
        except (UnicodeError, ValueError, TypeError):
            return login_page(True)
        target = safe_next(fields.get('next',[''])[0]) or ('/?research=1' if user['role']=='researcher' else '/')
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(COOKIE, token_for(name,user,cfg), httponly=True, samesite='strict', max_age=43200,
            secure=request.url.scheme=='https' or request.headers.get('x-forwarded-proto')=='https')
        response.headers['Cache-Control'] = 'no-store'
        return response
    who = principal(request,cfg)
    if not who:
        if route == '/' and request.method == 'GET':
            suffix='?next='+quote('/?'+request.url.query,safe='') if request.url.query else ''
            return RedirectResponse('/login'+suffix,status_code=303)
        if getattr(request.state,'auth_throttled',False):
            return JSONResponse({'detail':'접속 시도가 많습니다. 잠시 후 다시 시도해 주세요.'},status_code=429,headers={'Retry-After':'60'})
        return JSONResponse({'detail':'팀 접속이 필요합니다.'},status_code=401)
    request.state.access_role = who['role']
    request.state.access_identity = who
    if route == '/auth/logout' and request.method == 'POST':
        response = RedirectResponse('/login',status_code=303)
        response.delete_cookie(COOKIE)
        return response
    if who['role'] == 'participant' and (route in ('/api/replay','/docs','/redoc','/openapi.json')
            or route.startswith('/api/prototype/')
            or route.startswith('/api/task-candidates')
            or route.startswith('/api/pilot/')
            or route.endswith(('/research-code','/export','/condition'))):
        return JSONResponse({'detail':'연구자 권한이 필요합니다.'},status_code=403)
    if who.get('pilot') and request.method=='POST' and (route=='/api/sessions' or route.startswith('/api/demo')):
        return JSONResponse({'detail':'배정된 과제를 순서대로 진행하세요.'},status_code=403)
    return None
