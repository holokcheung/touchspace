"""Bound multipart bodies before FastAPI's form parser spools any file uploads."""
from __future__ import annotations

import tempfile

from starlette.responses import JSONResponse

from .package import MAX_BYTES


class PackageSizeLimit:
    def __init__(self, app, max_bytes: int = MAX_BYTES + 128 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'].rstrip('/') != '/api/touchspace/maps':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = self.max_bytes + 1

        async def reject():
            response = JSONResponse({'error': {'code': 'file_too_large', 'message': 'Map uploads must be at most 64 MiB plus multipart headers.', 'details': None}}, status_code=413)
            await response(scope, receive, send)

        if declared > self.max_bytes or declared < 0:
            return await reject()
        # Spill to a bounded temporary file instead of retaining another full package in memory.
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            size = 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > self.max_bytes:
                    return await reject()
                body.write(chunk)
                if not message.get('more_body', False):
                    break
            body.seek(0)

            async def bounded_receive():
                chunk = body.read(64 * 1024)
                return {'type': 'http.request', 'body': chunk, 'more_body': body.tell() < size}

            await self.app(scope, bounded_receive, send)
