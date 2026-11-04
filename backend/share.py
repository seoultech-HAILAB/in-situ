"""Public participant gateway; research/admin/legacy APIs stay on loopback.

uvicorn backend.share:app --host 0.0.0.0 --port 8003
The existing backend keeps the API key and performs all LLM requests.
"""
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, RedirectResponse

UPSTREAM = os.getenv('TRACE_UPSTREAM', 'http://127.0.0.1:8002').rstrip('/')


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(base_url=UPSTREAM, timeout=180, trust_env=False) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
UUID = r'[a-f0-9-]{36}'


def allowed(method, path):
    if method in ('GET', 'HEAD'):
        return (path in ('/in-situ', '/ex-situ', '/api/health', '/favicon.ico', '/icon.svg') or
                path.startswith('/_next/') or
                re.fullmatch(rf'/api/experiments/{UUID}', path) is not None or
                re.fullmatch(rf'/api/sessions/{UUID}(/output\.csv)?', path) is not None)
    if method == 'POST':
        return (path == '/api/experiments' or
                re.fullmatch(rf'/api/experiments/{UUID}/(events|action)', path) is not None or
                re.fullmatch(rf'/api/sessions/{UUID}/(explanations|execution-observations|undo|revision-preview)', path) is not None or
                re.fullmatch(rf'/api/sessions/{UUID}/revision-preview/{UUID}/(explanations|approve|deny)', path) is not None)
    return False


@app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
async def proxy(path: str, request: Request):
    path = '/' + path
    if path == '/' and request.method == 'GET':
        return RedirectResponse('/in-situ')
    if not allowed(request.method, path) or request.query_params.get('research'):
        return Response('Not Found', status_code=404)
    origin = request.headers.get('origin')
    if request.method == 'POST' and origin and origin != str(request.base_url).rstrip('/'):
        return Response('허용되지 않은 출처입니다.', status_code=403)
    if path.startswith('/api/sessions/') and not all(request.headers.get(key) for key in ('x-study-id', 'x-study-token')):
        return Response('실험 접속 정보가 필요합니다.', status_code=403)
    try:
        length = int(request.headers.get('content-length') or 0)
    except ValueError:
        return Response('잘못된 요청입니다.', status_code=400)
    if length > 2_000_000:
        return Response('요청 크기가 너무 큽니다.', status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2_000_000:
            return Response('요청 크기가 너무 큽니다.', status_code=413)
    headers = {key: request.headers[key] for key in
               ('content-type', 'x-study-id', 'x-study-token', 'x-request-id') if key in request.headers}
    headers['x-trace-view'] = 'participant'
    try:
        result = await request.app.state.client.request(request.method, path, headers=headers, content=bytes(body))
    except httpx.HTTPError:
        return Response('실험 서버에 연결할 수 없습니다.', status_code=503)
    outgoing = {key: value for key, value in result.headers.items() if key in
                ('content-type', 'content-disposition', 'location', 'etag', 'last-modified')}
    outgoing.update({'Cache-Control': 'no-store' if path.startswith('/api/') else 'no-cache',
                     'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin'})
    return Response(result.content, status_code=result.status_code, headers=outgoing)
