"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload   (binds 127.0.0.1 by default)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from . import config
from .db import Base, get_engine, get_session_factory
from jinja2 import pass_context

from .money import format_int_lang, format_qty, format_qty2, format_sek_lang
from .swedish import format_date_sv

log = logging.getLogger("firma")

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def run_migrations() -> None:
    """Apply Alembic migrations; on a brand-new DB this creates everything.
    Falls back to create_all if Alembic is unavailable (dev convenience)."""
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(config.BASE_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(config.BASE_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", config.DATABASE_URL)
        command.upgrade(cfg, "head")
    except Exception as exc:  # pragma: no cover
        log.warning("Alembic migration failed (%s) — falling back to create_all", exc)
        Base.metadata.create_all(get_engine())


def seed_reference_data(db) -> None:
    """Idempotent seeding of VAT codes, company profile row and default
    expense categories."""
    from . import vat as vatmod
    from .models import CompanyProfile, ExpenseCategory, VatRate

    if db.get(CompanyProfile, 1) is None:
        db.add(CompanyProfile(id=1))

    existing_codes = {r[0] for r in db.execute(select(VatRate.code)).all()}
    order = 0
    for registry in (vatmod.SALE_CODES, vatmod.PURCHASE_CODES):
        for info in registry.values():
            if info.code in existing_codes:
                continue
            order += 10
            db.add(VatRate(
                code=info.code, label_sv=info.label_sv, percent=info.percent,
                side=info.side, skv_boxes=info.boxes_text, sort_order=info.sort_order * 10,
            ))

    default_categories = [
        ("Kontor & administration", "6100"),
        ("IT & programvara", "6500"),
        ("Telefon & internet", "6200"),
        ("Resor", "5800"),
        ("Bil & transport", "5600"),
        ("Marknadsföring", "5900"),
        ("Representation", "5720"),
        ("Lokal & hyra", "5000"),
        ("Varor & material", "4000"),
        ("Underentreprenörer", "4400"),
        ("Försäkringar", "5510"),
        ("Bank & kortavgifter", "6570"),
        ("Bokföring & revision", "6900"),
        ("Övrigt", ""),
    ]
    existing_cats = {r[0] for r in db.execute(select(ExpenseCategory.name)).all()}
    for name, bas in default_categories:
        if name not in existing_cats:
            db.add(ExpenseCategory(name=name, bas_account_hint=bas))
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    run_migrations()
    db = get_session_factory()()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    config.ensure_dirs()
    app = FastAPI(
        title="Firmabok — lokal bokföring för enskild firma",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,  # local tool: no public API docs
    )

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    @pass_context
    def _sek(ctx, value):
        return format_sek_lang(value, ctx.get("lang", "sv"), symbol=False)

    @pass_context
    def _money(ctx, value):
        return format_sek_lang(value, ctx.get("lang", "sv"), symbol=True)

    @pass_context
    def _kronor(ctx, value):
        return format_int_lang(value, ctx.get("lang", "sv"))

    templates.env.filters["sek"] = _sek
    templates.env.filters["money"] = _money
    templates.env.filters["kronor"] = _kronor
    templates.env.filters["qty"] = format_qty
    templates.env.filters["qty2"] = format_qty2
    templates.env.filters["dsv"] = format_date_sv
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/uploads", StaticFiles(directory=str(config.UPLOAD_DIR)), name="uploads")

    from .routers import (
        auth, customers, dashboard, data, expenses, income,
        invoices, owner, reports, settings, vat,
    )
    for r in (auth, dashboard, income, expenses, vat, invoices,
              customers, owner, reports, settings, data):
        app.include_router(r.router)

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        accept = request.headers.get("accept", "")
        if "application/json" in accept and "text/html" not in accept and "*/*" not in accept:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Inte inloggad"}, status_code=401)
        return RedirectResponse(url="/login?next=" + str(request.url.path), status_code=302)

    return app


app = create_app()
