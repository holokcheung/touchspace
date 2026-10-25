"""Bound upload bytes before the multipart parser spools files, including chunked bodies."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from .package import MAX_PACKAGE


class UploadTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413,"Map upload exceeds 64 MB")


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/api/touchspace/maps" or scope.get("method") != "POST":
            return await self.app(scope,receive,send)
        limit = MAX_PACKAGE + 64*1024
        headers = dict(scope.get("headers",[]))
        try:
            declared = int(headers.get(b"content-length",b"0"))
        except ValueError:
            return await JSONResponse({"detail":"Invalid Content-Length"},status_code=400)(scope,receive,send)
        async def reject():
            await JSONResponse({"detail":"Map upload exceeds 64 MB"},status_code=413)(scope,receive,send)
        if declared > limit:
            return await reject()
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body",b""))
                if total > limit:
                    raise UploadTooLarge()
            return message
        try:
            await self.app(scope,bounded_receive,send)
        except UploadTooLarge:
            await reject()
