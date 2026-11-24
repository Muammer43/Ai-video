from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import auth, compat, content, ops, projects
from .core import ratelimit
from .core.config import ensure_dirs, get_settings
from .core.errors import AppError
from .core.logging import setup_logging
from .database.session import create_all

log = logging.getLogger("aivf")
SEC_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
               "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
               "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: https:; style-src 'self' 'unsafe-inline'; "
                                          "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.validate_for_runtime()
    setup_logging()
    ensure_dirs(s)
    if s.database_url.startswith("sqlite") or s.env in ("dev", "test"):
        create_all()  # üretimde şema Alembic ile yönetilir (alembic upgrade head)
    if s.celery_eager and s.env != "test":  # Redis/beat yok: otomasyon, takılı iş toparlama ve zamanlanmış yayın için gömülü zamanlayıcı
        from .workers import embedded
        embedded.start()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.app_version, lifespan=lifespan,
                  description="AI Video Factory Pro V2 — otonom AI video üretim ve yayın platformu. Kimlik doğrulama: Bearer JWT (`/api/v1/auth/login`).",
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
    if s.cors_list():
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_list(), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        if request.url.path.startswith("/api/") and request.url.path not in ("/api/health",):
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
            ok, wait = ratelimit.hit(f"ip:{ip}", s.rate_limit_per_minute, 60)
            if not ok:
                return JSONResponse({"error": {"code": "rate_limited", "message": f"Çok fazla istek; {wait} sn sonra deneyin"}}, status_code=429,
                                    headers={"Retry-After": str(wait)})
        if request.method in ("POST", "PUT") and int(request.headers.get("content-length") or 0) > 30 * 1024 * 1024:
            return JSONResponse({"error": {"code": "payload_too_large", "message": "İstek çok büyük"}}, status_code=413)
        resp = await call_next(request)
        for k, v in SEC_HEADERS.items():
            if request.url.path in ("/docs", "/redoc") and k == "Content-Security-Policy":
                continue
            resp.headers.setdefault(k, v)
        if s.public_base_url.startswith("https://"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers["X-Request-ID"] = rid
        log.info("%s %s %s %.0fms", request.method, request.url.path, resp.status_code, (time.monotonic() - t0) * 1000)
        return resp

    @app.exception_handler(AppError)
    async def app_error(_: Request, e: AppError):
        return JSONResponse({"error": {"code": e.code, "message": e.message, **({"data": e.data} if e.data else {})}}, status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, e: RequestValidationError):
        errs = [{"field": ".".join(str(x) for x in err["loc"][1:]), "message": err["msg"]} for err in e.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Geçersiz istek", "data": {"errors": errs}}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        return JSONResponse({"error": {"code": f"http_{e.status_code}", "message": str(e.detail)}}, status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, e: Exception):
        log.exception("işlenmeyen hata %s", request.url.path)
        return JSONResponse({"error": {"code": "internal_error", "message": "Beklenmeyen sunucu hatası"}}, status_code=500)

    v1 = "/api/v1"
    for r in (auth.router, projects.router, content.router, ops.router):
        app.include_router(r, prefix=v1)
    app.include_router(ops.public_router, prefix=v1)
    app.include_router(compat.router)

    @app.get(f"{v1}/health", tags=["system"])
    def health_v1():
        return {"ok": True, "version": s.app_version}

    fe = Path(__file__).resolve().parent.parent / "frontend"
    if fe.is_dir() and (fe / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(fe), html=True), name="frontend")
    return app


app = create_app()
