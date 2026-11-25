import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError

from .core.config import settings
from .core.logging import setup_logging
from .core.database import init_db
from .services.call_e_service import CallEError
from .api.routes import router as api_router, engine, calle_service, llm_service

logger = setup_logging(settings.log_level)
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "Starting RestartAI (mode=%s, host=%s:%s)...",
        settings.call_e_mode,
        settings.app_host,
        settings.app_port,
    )
    init_db(settings.db_path, settings.database_url)
    if settings.is_postgres:
        logger.info(
            "PostgreSQL database verified at %s", settings.database_url.split("@")[-1]
        )
    else:
        logger.info("SQLite database verified at %s", settings.db_path)
    yield
    # Shutdown
    logger.info("Shutting down RestartAI...")


app = FastAPI(
    title="RestartAI — Emergency Production Recovery Agent",
    description="Automated emergency parts recovery: detect failure, call suppliers, plan recovery, human-approved dispatch.",
    lifespan=lifespan,
)

# Static and Templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include API Router
app.include_router(api_router)


# Exception Handlers
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"success": False, "error": "Invalid request.", "details": exc.errors()},
        status_code=422,
    )


@app.exception_handler(ValueError)
async def value_error(request: Request, exc: ValueError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.exception_handler(RuntimeError)
async def runtime_error(request: Request, exc: RuntimeError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=502)


@app.exception_handler(CallEError)
async def calle_error(request: Request, exc: CallEError):
    return JSONResponse(
        {"success": False, "error": str(exc), "code": exc.code}, status_code=502
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled API error path=%s", request.url.path)
    return JSONResponse(
        {
            "success": False,
            "error": "RestartAI encountered an unexpected server error.",
            "detail": str(exc)[:500],
        },
        status_code=500,
    )


# Root View
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"request": request}
    )


@app.get("/logs")
def logs_page():
    return RedirectResponse(url="/#/logs")


@app.get("/approver/{run_id}", response_class=HTMLResponse)
def mobile_approver(run_id: str):
    from .api.routes import action_service, engine

    run_state = engine.get(run_id)
    if not run_state:
        return HTMLResponse("<h1>Recovery Run Not Found</h1>", status_code=404)
    return HTMLResponse(action_service.render_mobile_approver_html(run_state))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host=settings.app_host, port=settings.app_port, reload=True
    )
