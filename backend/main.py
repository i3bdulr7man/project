from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import RedirectResponse
from routes import user, admin

app = FastAPI()

# Middleware لإجبار HTTPS عبر Cloudflare (بناءً على X-Forwarded-Proto)
class EnforceHTTPSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("x-forwarded-proto") != "https":
            url = request.url.replace(scheme="https")
            return RedirectResponse(url=str(url))
        return await call_next(request)

app.add_middleware(EnforceHTTPSMiddleware)

app.include_router(user.router)
app.include_router(admin.router)
