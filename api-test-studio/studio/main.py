from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contracts import VERSION

from . import config
from .db import init_db
from .routers import auth, cases, flows, framework, helper, jobs, projects, roles, scripts, specs, unit


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title='API Test Studio', version=VERSION, lifespan=lifespan)
for module in (auth, projects, specs, framework, unit, flows, roles, scripts, cases, helper, jobs):
    app.include_router(module.router)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = '.'.join(str(part) for part in first.get('loc', [])[1:]) or 'request'
    message = f"{field}: {first.get('msg', 'invalid value')}"
    return JSONResponse(status_code=422, content={'detail': message, 'errors': errors[:20]}, )


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'")
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': VERSION}


if (config.WEB_DIST / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=config.WEB_DIST / 'assets'), name='assets')


@app.get('/{full_path:path}', include_in_schema=False)
def single_page_app(full_path: str):
    if full_path.startswith('api/'):
        raise HTTPException(404, 'Not found.')
    static = (config.WEB_DIST / full_path).resolve()
    if full_path and static.is_file() and static.is_relative_to(config.WEB_DIST.resolve()):
        return FileResponse(static)
    index = config.WEB_DIST / 'index.html'
    if not index.is_file():
        return JSONResponse(status_code=503, content={'detail': 'The web app is not built yet. Run: cd web; npm install; npm run build'})
    return FileResponse(index)
