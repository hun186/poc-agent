"""Cap Product preview request bodies before FastAPI's multipart parser spools files.

This deliberately applies only to the P2.1 preview route. The full bounded
body is read at the ASGI boundary; a too-large upload never reaches Starlette's
UploadFile spooling or form parsing. The cap includes multipart framing.
"""
from __future__ import annotations


class ProductPreviewBodyLimitMiddleware:
    MAX_BODY_BYTES = 11 * 1024 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http"
                or scope.get("method") != "POST"
                or scope.get("path") != "/v1/requirement-task-previews"):
            await self.app(scope, receive, send)
            return

        async def reject():
            body = b'{"detail":{"code":"requirement_preview_input_invalid"}}'
            await send({
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})

        for name, value in scope.get("headers", ()):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await reject()
                    return
                if declared < 0 or declared > self.MAX_BODY_BYTES:
                    await reject()
                    return

        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            data = message.get("body", b"")
            size += len(data)
            if size > self.MAX_BODY_BYTES:
                await reject()
                return
            chunks.append(message)
            if not message.get("more_body", False):
                break

        position = 0

        async def replay():
            nonlocal position
            if position < len(chunks):
                message = chunks[position]
                position += 1
                return message
            return await receive()

        await self.app(scope, replay, send)
