"""Bound upload bytes before the multipart parser spools files, including chunked bodies."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from .package import MAX_PACKAGE


class UploadTooLarge(HTTPException):
    def __init__(self, detail="Map upload exceeds 64 MB"):
        super().__init__(413, detail)


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path")
        if scope["type"] != "http" or path not in ("/api/touchspace/maps", "/api/touchspace/chat") or scope.get("method") != "POST":
            return await self.app(scope,receive,send)
        limit = 2*1024*1024 if path.endswith("/chat") else MAX_PACKAGE + 64*1024
        detail = "Chat map context exceeds 2 MB" if path.endswith("/chat") else "Map upload exceeds 64 MB"
        headers = dict(scope.get("headers",[]))
        try:
            declared = int(headers.get(b"content-length",b"0"))
        except ValueError:
            return await JSONResponse({"detail":"Invalid Content-Length"},status_code=400)(scope,receive,send)
        async def reject():
            await JSONResponse({"detail":detail},status_code=413)(scope,receive,send)
        if declared > limit:
            return await reject()
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body",b""))
                if total > limit:
                    raise UploadTooLarge(detail)
            return message
        try:
            await self.app(scope,bounded_receive,send)
        except UploadTooLarge:
            await reject()
