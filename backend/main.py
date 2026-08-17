"""AI LaTeX Resume Maker API."""

from __future__ import annotations

import base64
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from core.compiler import compiler, CompilationError
    from core.ai_agent import ai_agent
    from core.templates import template_manager
    from core.parser import sectional_parser
    from core.ats_scorer import ats_scorer
    from core.indent_guard import indent_guard
    from core.refinement import refinement_manager, DraftVariant
    from core.session_store import (
        session_store,
        take_snapshot,
        rollback_to_snapshot,
    )
    from core.zones import zone_engine
    from core.logging_setup import get_logger, setup_logging
    from core.auth_store import auth_store
    from core.latex_to_zones import latex_to_zones
    from core.overleaf_import import (
        import_overleaf_url,
        OverleafImportError,
        validate_overleaf_url,
        ImportResult,
    )
    from core.zone_document import (
        ZoneDocument,
        document_from_session,
        sync_session_from_document,
        ensure_full_document,
    )
    from core.latex_soften import soften_latex_for_tectonic
    from core import config
    from llm_router import llm_router, SUPPORTED_PROVIDERS
except ImportError:
    from .core.compiler import compiler, CompilationError
    from .core.ai_agent import ai_agent
    from .core.templates import template_manager
    from .core.parser import sectional_parser
    from .core.ats_scorer import ats_scorer
    from .core.indent_guard import indent_guard
    from .core.refinement import refinement_manager, DraftVariant
    from .core.session_store import (
        session_store,
        take_snapshot,
        rollback_to_snapshot,
    )
    from .core.zones import zone_engine
    from .core.logging_setup import get_logger, setup_logging
    from .core.auth_store import auth_store
    from .core.latex_to_zones import latex_to_zones
    from .core.overleaf_import import (
        import_overleaf_url,
        OverleafImportError,
        validate_overleaf_url,
        ImportResult,
    )
    from .core.zone_document import (
        ZoneDocument,
        document_from_session,
        sync_session_from_document,
        ensure_full_document,
    )
    from .core.latex_soften import soften_latex_for_tectonic
    from .core import config
    from .llm_router import llm_router, SUPPORTED_PROVIDERS

setup_logging()
log = get_logger("api")
log.info(
    "api boot environment=%s log_level=%s",
    getattr(config, "ENVIRONMENT", "development"),
    getattr(config, "LOG_LEVEL", "INFO"),
)

# Ensure Windows Fontconfig is ready before any compile requests
try:
    from core.compiler import apply_fontconfig_env, ensure_fontconfig_files

    conf = ensure_fontconfig_files()
    apply_fontconfig_env()
    log.info("fontconfig: ready file=%s", conf)
except Exception as _fc_err:  # pragma: no cover
    try:
        from .core.compiler import apply_fontconfig_env, ensure_fontconfig_files

        conf = ensure_fontconfig_files()
        apply_fontconfig_env()
        log.info("fontconfig: ready file=%s", conf)
    except Exception as e:
        log.warning("fontconfig: setup failed - %s", e)


def _mask_key(key: Optional[str]) -> str:
    if not key or not key.strip():
        return "(none)"
    k = key.strip()
    if len(k) <= 8:
        return "***"
    return f"{k[:4]}...{k[-4:]} (len={len(k)})"


app = FastAPI(
    title="AI LaTeX Resume Maker API",
    description="Agentic resume builder with multi-provider LLM router",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    log.info("-> %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        raise
    level = log.warning if response.status_code >= 400 else log.info
    level("<- %s %s %s", response.status_code, request.method, request.url.path)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    log.error(
        "HTTP %s on %s %s - %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception(
        "Unhandled %s on %s %s: %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc,
    )
    try:
        from core.logging_setup import debug_exception
    except ImportError:
        from .core.logging_setup import debug_exception
    try:
        debug_exception(exc, logger=log)
    except Exception:
        log.debug("rich traceback unavailable\n%s", traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


# ---------- Request models ----------


class GenerateRequest(BaseModel):
    bio: str
    template_name: str = "modern"
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ProposalRequest(BaseModel):
    current_latex: str
    command: str
    section_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ApplyRequest(BaseModel):
    session_id: str
    variant_id: str
    current_latex: str
    section_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ScoreRequest(BaseModel):
    resume_text: str
    job_description: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class CompileRequest(BaseModel):
    latex_code: str
    project_dir: Optional[str] = None
    session_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    template_name: str = "modern"
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    source_url: Optional[str] = None
    latex: Optional[str] = None
    # Optional zone filter (zone-selection path)
    included_zone_nos: Optional[List[int]] = None
    zone_order: Optional[List[int]] = None
    custom_zones: Optional[List[str]] = None


class SetupImportRequest(BaseModel):
    url: Optional[str] = None
    latex: Optional[str] = None
    template_name: Optional[str] = None


class SessionSetupRequest(BaseModel):
    included_zone_nos: Optional[List[int]] = None
    zone_order: Optional[List[int]] = None
    source_url: Optional[str] = None
    latex: Optional[str] = None


class AddZoneRequest(BaseModel):
    description: str = "Custom section"
    after_zone_no: Optional[int] = None
    at_start: bool = False
    latex_inner: Optional[str] = None


class ZoneOrderRequest(BaseModel):
    zone_order: List[int]


class ChatRequest(BaseModel):
    session_id: str
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None
    template_name: Optional[str] = None
    api_key: Optional[str] = None


class ModelPatchRequest(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None


class LatexPutRequest(BaseModel):
    latex_code: str


class ApplyChatProposalRequest(BaseModel):
    session_id: str
    proposal_session_id: str
    variant_id: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


# ---------- Helpers ----------


def _resolve_llm(
    provider: Optional[str], model: Optional[str], session=None
):
    p = provider or (session.active_provider if session else None) or config.LLM_PROVIDER
    m = model or (session.active_model if session else None) or config.MODEL_NAME
    return p, m


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return authorization.strip() or None


def _resolve_api_key(
    *,
    provider: str,
    request_key: Optional[str],
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Prefer request api_key, then logged-in profile key."""
    if request_key and request_key.strip():
        return request_key.strip()
    user = auth_store.user_from_token(_token_from_header(authorization))
    profile_key = auth_store.get_api_key(user, provider)
    if profile_key:
        log.info(
            "auth: using profile key for user=%s provider=%s",
            user.username if user else "?",
            provider,
        )
    return profile_key


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileKeysRequest(BaseModel):
    api_keys: Dict[str, str] = Field(default_factory=dict)
    clear_keys: List[str] = Field(default_factory=list)
    default_provider: Optional[str] = None
    default_model: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def compile_with_retry(
    latex_code: str,
    max_retries: int = 2,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> tuple:
    """Compile LaTeX; on failure ask the agent to fix. Returns (pdf_bytes, latex)."""
    current_latex = ensure_full_document(latex_code or "")
    last_error = ""
    log.info(
        "compile_retry.step: start attempts=%s chars=%s project_dir=%s",
        max_retries + 1,
        len(current_latex),
        bool(project_dir),
    )

    for attempt in range(max_retries + 1):
        try:
            pdf = compiler.compile(current_latex, project_dir=project_dir)
            log.info(
                "compile_retry.step: ok attempt=%s pdf_bytes=%s",
                attempt,
                len(pdf),
            )
            return (pdf, current_latex)
        except CompilationError as e:
            log.error(
                "compile_retry.error: attempt=%s/%s - %s\n%s",
                attempt,
                max_retries,
                e,
                (e.logs or "")[-800:],
            )
            if attempt == max_retries:
                raise e
            last_error = e.logs
            log.info("compile_retry.step: asking agent to fix latex …")
            try:
                fix_update = ai_agent.fix_latex_error(
                    current_latex,
                    last_error,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                )
                current_latex = fix_update.latex_code
                log.info(
                    "compile_retry.step: fixer returned chars=%s "
                    "zones_changed=%s summary=%s",
                    len(current_latex),
                    fix_update.zones_changed or [],
                    (fix_update.summary_of_changes or "")[:120],
                )
            except Exception as fix_err:
                log.exception(
                    "compile_retry.error: fixer failed - %s", fix_err
                )
                raise e


    log.error("compile_retry.error: max retries exceeded")
    raise Exception("Max retries exceeded in compilation loop.")


def _pdf_b64(pdf_bytes: bytes) -> str:
    return base64.b64encode(pdf_bytes).decode("utf-8")


# ---------- Routes ----------


@app.get("/")
async def root():
    return {
        "message": "AI LaTeX Resume Maker API is running",
        "version": "2.0.0",
        "default_provider": config.LLM_PROVIDER,
        "default_model": config.MODEL_NAME,
    }


@app.get("/providers")
async def list_providers():
    return {
        "supported": list(SUPPORTED_PROVIDERS),
        "configured": llm_router.list_configured(),
        "default_provider": config.LLM_PROVIDER,
        "default_model": config.MODEL_NAME,
    }


# ---------- Auth / profile ----------


@app.post("/auth/register")
async def register(req: RegisterRequest):
    try:
        user = auth_store.register(req.username, req.password)
        token = auth_store.create_token(user.username)
        log.info("auth: registered user=%s", user.username)
        return {
            "token": token,
            "profile": user.public_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
async def login(req: LoginRequest):
    try:
        user = auth_store.authenticate(req.username, req.password)
        token = auth_store.create_token(user.username)
        log.info("auth: login user=%s", user.username)
        return {
            "token": token,
            "profile": user.public_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None)):
    token = _token_from_header(authorization)
    if token:
        auth_store.revoke_token(token)
        log.info("auth: logout")
    return {"ok": True}


@app.get("/auth/me")
async def auth_me(authorization: Optional[str] = Header(default=None)):
    user = auth_store.user_from_token(_token_from_header(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user.public_dict()


@app.put("/auth/profile/keys")
async def save_profile_keys(
    req: ProfileKeysRequest,
    authorization: Optional[str] = Header(default=None),
):
    user = auth_store.user_from_token(_token_from_header(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")

    incoming = {
        p: k for p, k in (req.api_keys or {}).items() if (k or "").strip()
    }
    user = auth_store.set_api_keys(
        user, incoming, clear=req.clear_keys or []
    )
    if req.default_provider:
        user.default_provider = req.default_provider.strip().lower()
    if req.default_model:
        user.default_model = req.default_model.strip()
    user = auth_store.save_user(user)
    log.info(
        "auth: saved keys user=%s updated=%s cleared=%s",
        user.username,
        list(incoming.keys()),
        req.clear_keys,
    )
    return user.public_dict()


@app.post("/auth/profile/password")
async def change_password(
    req: ChangePasswordRequest,
    authorization: Optional[str] = Header(default=None),
):
    user = auth_store.user_from_token(_token_from_header(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        auth_store.change_password(
            user, req.current_password, req.new_password
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log.info("auth: password changed user=%s", user.username)
    return {"ok": True, "detail": "Password updated"}


@app.post("/compile")
async def compile_latex_direct(req: CompileRequest):
    log.info(
        "compile.step: request session=%s raw_chars=%s",
        req.session_id,
        len(req.latex_code or ""),
    )
    latex = ensure_full_document(req.latex_code or "")
    project_dir = req.project_dir
    if not project_dir and req.session_id:
        sess = session_store.get(req.session_id)
        if sess:
            project_dir = getattr(sess, "project_dir", None)
    log.info(
        "compile.step: soften/shell ok chars=%s has_begin=%s project_dir=%s",
        len(latex),
        "\\begin{document}" in latex,
        bool(project_dir),
    )
    try:
        pdf_bytes = compiler.compile(latex, project_dir=project_dir)
        log.info("compile.step: ok pdf_bytes=%s", len(pdf_bytes))
        return {
            "pdf_base64": _pdf_b64(pdf_bytes),
            "latex_code": latex,
            "compile_error": None,
        }
    except CompilationError as e:
        log.error(
            "compile.error: tectonic failed - %s\n%s",
            e.message,
            (e.logs or "")[:2000],
        )
        tip = ""
        if "Fontconfig" in (e.logs or ""):
            tip = (
                " Tip: Fontconfig was configured under backend/fonts — "
                "restart the backend. If this is a font-heavy template, "
                "try a simpler Overleaf gallery CV or the bundled modern template."
            )
        tip += _tectonic_crash_tip(e.logs or "")
        return {
            "pdf_base64": None,
            "latex_code": latex,
            "compile_error": (
                f"Tectonic failed: {e.message}. {(e.logs or '')[:500]}{tip}"
            ),
        }
    except Exception as e:
        log.exception("compile.error: unexpected - %s", e)
        return {
            "pdf_base64": None,
            "latex_code": latex,
            "compile_error": str(e),
        }


@app.post("/generate")
async def generate_resume(req: GenerateRequest):
    template = template_manager.get_template(req.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    provider, model = _resolve_llm(req.provider, req.model)
    try:
        update = ai_agent.generate_initial_resume(
            req.bio,
            template,
            provider=provider,
            model=model,
            api_key=req.api_key,
        )
        pdf_bytes, latex = compile_with_retry(
            update.latex_code,
            provider=provider,
            model=model,
            api_key=req.api_key,
        )
        return {
            "latex_code": latex,
            "pdf_base64": _pdf_b64(pdf_bytes),
            "summary": update.summary_of_changes,
            "zones_changed": update.zones_changed,
            "provider": provider,
            "model": model,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/propose")
async def propose_edits(req: ProposalRequest):
    provider, model = _resolve_llm(req.provider, req.model)
    try:
        session_id = str(uuid.uuid4())
        proposal = ai_agent.generate_edit_proposals(
            req.current_latex,
            req.command,
            req.section_name,
            provider=provider,
            model=model,
            api_key=req.api_key,
        )
        variants = [
            DraftVariant(
                id=v.id,
                latex_code=v.latex_code,
                summary=v.summary,
                intent=v.intent,
                zone_id=v.zone_id,
            )
            for v in proposal.proposals
        ]
        refinement_manager.create_session(
            session_id, req.current_latex, variants
        )
        return {
            "session_id": session_id,
            "variants": [
                {
                    "id": v.id,
                    "intent": v.intent,
                    "summary": v.summary,
                    "latex_code": v.latex_code,
                    "zone_id": v.zone_id,
                }
                for v in proposal.proposals
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/apply")
async def apply_edit(req: ApplyRequest):
    provider, model = _resolve_llm(req.provider, req.model)
    try:
        variant = refinement_manager.get_variant(
            req.session_id, req.variant_id
        )
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        target_latex = req.current_latex
        section = req.section_name or variant.zone_id
        zones = zone_engine.list_zones(target_latex)
        is_fragment = "\\documentclass" not in (variant.latex_code or "")

        if section and section in zones:
            new_latex = zone_engine.replace_zone(
                target_latex, section, variant.latex_code
            )
        elif section and not is_fragment:
            new_latex = sectional_parser.replace_section(
                target_latex, section, variant.latex_code
            )
        elif is_fragment and zones:
            zone_id = "EXPERIENCE" if "EXPERIENCE" in zones else zones[0]
            new_latex = zone_engine.replace_zone(
                target_latex, zone_id, variant.latex_code
            )
        elif not is_fragment:
            new_latex = variant.latex_code
        else:
            raise HTTPException(
                status_code=400,
                detail="Cannot apply zone fragment: no zones in document",
            )

        compile_error = None
        pdf_b64 = None
        latex = new_latex
        try:
            pdf_bytes, latex = compile_with_retry(
                new_latex,
                provider=provider,
                model=model,
                api_key=req.api_key,
            )
            pdf_b64 = _pdf_b64(pdf_bytes)
        except Exception as e:
            compile_error = str(e)
            log.error("apply: compile failed - %s", e)

        return {
            "latex_code": latex,
            "pdf_base64": pdf_b64,
            "summary": variant.summary,
            "compile_error": compile_error,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("apply.error: unexpected - %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/score")
async def score_resume(
    req: ScoreRequest,
    authorization: Optional[str] = Header(default=None),
):
    provider, model = _resolve_llm(req.provider, req.model)
    api_key = _resolve_api_key(
        provider=provider,
        request_key=req.api_key,
        authorization=authorization,
    )
    try:
        return ats_scorer.calculate_score(
            req.resume_text,
            req.job_description,
            provider=provider,
            model=model,
            api_key=api_key,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate")
async def validate_latex(req: dict):
    try:
        latex = req.get("latex_code", "")
        health = indent_guard.validate_indentation(latex)
        ok, zone_issues = zone_engine.validate(latex)
        health["zone_ok"] = ok
        health["zone_issues"] = zone_issues
        return health
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sections")
async def get_sections(req: dict):
    try:
        latex = req.get("latex_code", "")
        session_id = req.get("session_id")
        zones = zone_engine.list_zones(latex)
        sections = sectional_parser.extract_sections(latex)
        catalog = []
        if session_id:
            session = session_store.get(session_id)
            if session and session.zones:
                order = session.zone_order or [
                    z.get("zone_no") for z in session.zones
                ]
                zmap = {z.get("zone_no"): z for z in session.zones}
                for n in order:
                    z = zmap.get(n)
                    if z:
                        catalog.append(
                            {
                                "zone_no": z.get("zone_no"),
                                "description": z.get("description"),
                                "kind": z.get("kind"),
                            }
                        )
        if not catalog and zones:
            catalog = [
                {"zone_no": z, "description": str(z), "kind": "legacy"}
                for z in zones
            ]
        return {
            "sections": list(sections.keys()),
            "zones": zones,
            "catalog": catalog,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/squeeze")
async def squeeze_resume(
    req: dict,
    authorization: Optional[str] = Header(default=None),
):
    try:
        latex = req.get("latex_code", "")
        provider, model = _resolve_llm(
            req.get("provider"), req.get("model")
        )
        api_key = _resolve_api_key(
            provider=provider,
            request_key=req.get("api_key"),
            authorization=authorization,
        )
        update = ai_agent.squeeze_layout(
            latex, provider=provider, model=model, api_key=api_key
        )
        pdf_bytes, out = compile_with_retry(
            update.latex_code,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        return {
            "latex_code": out,
            "pdf_base64": _pdf_b64(pdf_bytes),
            "summary": update.summary_of_changes,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Sessions + Chat ----------


def _tectonic_crash_tip(logs: str) -> str:
    """Tip only for silent/heap crashes — never when TeX reported a real error."""
    body = (logs or "").strip()
    lower = body.lower()
    # Real diagnostics: keep the tip off so we don't mislead.
    if any(
        tok in lower
        for tok in (
            "error:",
            "too many",
            "undefined control sequence",
            "missing \\begin{document}",
            "emergency stop",
            "file not found",
        )
    ):
        return ""
    # Heap crash pattern: almost empty log after "Running TeX"
    if (not body) or (
        "running tex" in lower and len(body) < 280 and "error" not in lower
    ):
        return (
            " Likely an incompatible Overleaf package (fontawesome / FiraMono / "
            "contour / fontspec) crashed Tectonic. Soften should strip these on "
            "paste — start a New chat and paste again, or use a public gallery "
            "zip URL so assets resolve."
        )
    return ""

def _doc_from_import(
    *,
    url: Optional[str] = None,
    latex: Optional[str] = None,
    template_name: Optional[str] = None,
) -> Tuple[ZoneDocument, Optional[str], List[str], List[str]]:
    """
    Returns (document, project_dir, warnings, compat_notes).
    project_dir is set when an Overleaf/GitHub zip with assets was downloaded.
    Softens Overleaf packages before zoning so Windows Tectonic can compile.
    """
    log.info(
        "import.step: start url=%s latex_chars=%s template=%s",
        bool(url),
        len(latex or ""),
        template_name,
    )
    source_url = url
    project_dir: Optional[str] = None
    warnings: List[str] = []
    compat_notes: List[str] = []
    if url and not latex:
        try:
            log.info("import.step: validate+download overleaf url")
            validate_overleaf_url(url)
            result: ImportResult = import_overleaf_url(url)
            latex = result.latex
            source_url = result.source_url
            project_dir = result.project_dir
            warnings = list(result.warnings)
            if result.main_tex:
                warnings.append(f"Main file: {result.main_tex}")
            if result.files:
                warnings.append(f"Imported {len(result.files)} files")
            log.info(
                "import.step: download ok latex_chars=%s project_dir=%s",
                len(latex or ""),
                bool(project_dir),
            )
        except OverleafImportError as e:
            log.error("import.error: overleaf failed - %s", e)
            raise HTTPException(status_code=400, detail=str(e))
    if not latex and template_name:
        log.info("import.step: load bundled template=%s", template_name)
        latex = template_manager.get_template(template_name)
    if not latex:
        log.error("import.error: no latex/url/template provided")
        raise HTTPException(
            status_code=400,
            detail="Provide overleaf url, latex, or template_name",
        )
    latex, compat_notes = soften_latex_for_tectonic(latex)
    if compat_notes:
        log.info("import.step: softened changes=%s", compat_notes)
        warnings.append(
            "Adjusted for Windows Tectonic: " + "; ".join(compat_notes)
        )
    try:
        doc = latex_to_zones(latex, source_url=source_url)
        log.info(
            "import.step: zones ready count=%s order=%s",
            len(doc.zones),
            doc.zone_order,
        )
    except Exception as e:
        log.exception("import.error: latex_to_zones failed - %s", e)
        raise HTTPException(
            status_code=400, detail=f"Failed to parse LaTeX into zones: {e}"
        )
    return doc, project_dir, warnings, compat_notes


@app.post("/setup/import")
async def setup_import(req: SetupImportRequest):
    """Convert Overleaf URL / pasted LaTeX / bundled template → zones JSON."""
    log.info(
        "setup.import: url=%s latex=%s template=%s",
        bool(req.url),
        bool(req.latex),
        req.template_name,
    )
    doc, project_dir, warnings, compat_notes = _doc_from_import(
        url=req.url,
        latex=req.latex,
        template_name=req.template_name or (
            "modern" if not req.url and not req.latex else None
        ),
    )
    # Soft compile check so UI knows if format can render
    compile_error = None
    pdf_b64 = None
    assembled = ensure_full_document(doc.assemble())
    log.info(
        "setup.import: assemble ok chars=%s zones=%s compiling…",
        len(assembled),
        doc.zone_order,
    )
    try:
        pdf_bytes = compiler.compile(assembled, project_dir=project_dir)
        pdf_b64 = _pdf_b64(pdf_bytes)
        log.info("setup.import: compile ok pdf_bytes=%s", len(pdf_bytes))
    except CompilationError as e:
        tip = _tectonic_crash_tip(e.logs or "")
        compile_error = f"Tectonic failed: {e.message}. {(e.logs or '')[:500]}{tip}"
        log.exception("setup.import: compile failed - %s", e)
        warnings.append(
            "Template imported but initial compile failed — "
            "chat can still edit; try Sync after setup."
        )
    except Exception as e:
        compile_error = str(e)
        log.exception("setup.import: compile failed - %s", e)
        warnings.append(
            "Template imported but initial compile failed — "
            "chat can still edit; try Sync after setup."
        )
    return {
        "document": doc.model_dump(),
        "catalog": doc.catalog(),
        "latex_code": assembled,
        "project_dir": project_dir,
        "warnings": warnings,
        "compat_notes": compat_notes,
        "pdf_base64": pdf_b64,
        "compile_error": compile_error,
    }


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    """
    Create a chat base from either:
    - template URL / pasted latex (`source_url` or `latex`), or
    - bundled template + optional zone selection (`template_name`,
      `included_zone_nos` / `zone_order` / `custom_zones`).
    """
    provider = req.provider or config.LLM_PROVIDER
    model = req.model or config.MODEL_NAME

    has_url = bool((req.source_url or "").strip())
    has_latex = bool((req.latex or "").strip())
    project_dir: Optional[str] = None
    log.info(
        "session.create: url=%s latex=%s template=%s included=%s",
        has_url,
        has_latex,
        req.template_name,
        req.included_zone_nos,
    )
    compat_notes: List[str] = []
    if has_url or has_latex:
        doc, project_dir, _warnings, compat_notes = _doc_from_import(
            url=req.source_url, latex=req.latex
        )
    else:
        template = template_manager.get_template(req.template_name)
        if not template:
            log.error("session.create: template not found %s", req.template_name)
            raise HTTPException(status_code=404, detail="Template not found")
        soft, compat_notes = soften_latex_for_tectonic(template)
        doc = latex_to_zones(soft)
        log.info("session.create: bundled template zones=%s", doc.zone_order)

    if req.source_url and not doc.source_url:
        doc.source_url = req.source_url

    if req.included_zone_nos is not None:
        keep = set(req.included_zone_nos)
        for n in list(doc.zone_order):
            if n not in keep:
                try:
                    doc.remove_zone(n)
                except KeyError:
                    pass

    if req.zone_order:
        remaining = [n for n in req.zone_order if n in doc.zone_map()]
        extras = [n for n in doc.zone_order if n not in remaining]
        doc.zone_order = remaining + extras

    for desc in req.custom_zones or []:
        name = (desc or "").strip()
        if not name:
            continue
        doc.add_zone(
            description=name,
            latex_inner=f"\\section*{{{name}}}\n% TODO",
            kind="custom",
        )

    assembled = ensure_full_document(doc.assemble())
    # Keep session latex aligned with softened/shell-fixed source
    if assembled != doc.assemble():
        try:
            doc = latex_to_zones(assembled, source_url=doc.source_url)
        except Exception:
            pass
    session = session_store.create(
        template_name=req.template_name,
        title=req.title or "New resume chat",
        latex_code=assembled,
        provider=provider,
        model=model,
        header=doc.header,
        footer=doc.footer,
        zones=[z.model_dump() for z in doc.zones],
        zone_order=list(doc.zone_order),
        next_zone_no=doc.next_zone_no,
        source_url=doc.source_url,
        project_dir=project_dir,
        setup_complete=True,
        welcome=(
            "Base ready. Paste your biodata to fill zones, or ask to "
            "add/remove/reorder/edit a zone."
        ),
    )
    log.info(
        "session.create: ok id=%s zones=%s project_dir=%s compat=%s",
        session.session_id,
        session.zone_order,
        bool(project_dir),
        compat_notes,
    )
    payload = session.model_dump()
    payload["compat_notes"] = compat_notes
    if compat_notes:
        payload["compat_banner"] = (
            "Adjusted for Windows Tectonic: " + "; ".join(compat_notes)
        )
    return payload


@app.post("/sessions/{session_id}/setup")
async def confirm_session_setup(session_id: str, req: SessionSetupRequest):
    session = session_store.get(session_id)
    if not session:
        log.error("session.setup: not found id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")
    log.info(
        "session.setup: id=%s included=%s order=%s",
        session_id,
        req.included_zone_nos,
        req.zone_order,
    )

    if req.latex or req.source_url:
        doc, project_dir, _warnings, _compat = _doc_from_import(
            url=req.source_url, latex=req.latex
        )
        if project_dir:
            session.project_dir = project_dir
    else:
        doc = document_from_session(session)
        if doc is None:
            template = template_manager.get_template(session.template_name)
            doc = latex_to_zones(template or session.latex_code)

    if req.included_zone_nos is not None:
        keep = set(req.included_zone_nos)
        for n in list(doc.zone_order):
            if n not in keep:
                try:
                    doc.remove_zone(n)
                except KeyError:
                    pass
    if req.zone_order:
        # Allow subset order of remaining zones
        remaining = [n for n in req.zone_order if n in doc.zone_map()]
        extras = [n for n in doc.zone_order if n not in remaining]
        doc.zone_order = remaining + extras

    sync_session_from_document(session, doc)
    session_store.save(session)
    return session.model_dump()


@app.post("/sessions/{session_id}/zones")
async def add_session_zone(session_id: str, req: AddZoneRequest):
    session = session_store.get(session_id)
    if not session:
        log.error("zones.add: session not found id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")
    log.info(
        "zones.add.step: id=%s desc=%s after=%s at_start=%s",
        session_id,
        req.description,
        req.after_zone_no,
        req.at_start,
    )
    doc = document_from_session(session) or latex_to_zones(
        session.latex_code
        or template_manager.get_template(session.template_name)
        or ""
    )
    inner = req.latex_inner or (
        f"\\section*{{{req.description}}}\n% TODO"
    )
    rec = doc.add_zone(
        description=req.description,
        latex_inner=inner,
        after_zone_no=req.after_zone_no,
        at_start=req.at_start,
    )
    sync_session_from_document(session, doc)
    session_store.save(session)
    log.info("zones.add.step: ok zone_no=%s order=%s", rec.zone_no, doc.zone_order)
    return {
        "zone": rec.model_dump(),
        "catalog": doc.catalog(),
        "latex_code": session.latex_code,
        "session": session.model_dump(),
    }


@app.delete("/sessions/{session_id}/zones/{zone_no}")
async def remove_session_zone(session_id: str, zone_no: int):
    session = session_store.get(session_id)
    if not session:
        log.error("zones.remove: session not found id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")
    doc = document_from_session(session)
    if doc is None:
        log.error("zones.remove: no zone document id=%s", session_id)
        raise HTTPException(status_code=400, detail="Session has no zone document")
    try:
        removed = doc.remove_zone(zone_no)
    except KeyError:
        log.error("zones.remove: zone %s not found id=%s", zone_no, session_id)
        raise HTTPException(status_code=404, detail=f"Zone {zone_no} not found")
    sync_session_from_document(session, doc)
    session_store.save(session)
    log.info(
        "zones.remove.step: ok zone=%s remaining=%s",
        zone_no,
        doc.zone_order,
    )
    return {
        "removed": removed.model_dump(),
        "catalog": doc.catalog(),
        "latex_code": session.latex_code,
        "session": session.model_dump(),
    }


@app.patch("/sessions/{session_id}/zone-order")
async def patch_zone_order(session_id: str, req: ZoneOrderRequest):
    session = session_store.get(session_id)
    if not session:
        log.error("zones.order: session not found id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")
    doc = document_from_session(session)
    if doc is None:
        log.error("zones.order: no zone document id=%s", session_id)
        raise HTTPException(status_code=400, detail="Session has no zone document")
    log.info("zones.order.step: id=%s → %s", session_id, req.zone_order)
    try:
        doc.reorder(req.zone_order)
    except ValueError as e:
        log.error("zones.order.error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    sync_session_from_document(session, doc)
    session_store.save(session)
    log.info("zones.order.step: ok order=%s", doc.zone_order)
    return {
        "zone_order": doc.zone_order,
        "catalog": doc.catalog(),
        "latex_code": session.latex_code,
        "session": session.model_dump(),
    }


@app.get("/sessions")
async def list_sessions():
    return {"sessions": session_store.list_sessions()}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if not session_store.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.patch("/sessions/{session_id}/model")
async def patch_session_model(session_id: str, req: ModelPatchRequest):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    provider = req.provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider. Use one of: {SUPPORTED_PROVIDERS}",
        )
    # Model switch only updates session metadata; key checked on /chat
    log.info(
        "session.model: id=%s provider=%s model=%s api_key=%s",
        session_id,
        provider,
        req.model,
        _mask_key(req.api_key),
    )
    session = session_store.set_model(session, provider, req.model.strip())
    return session.model_dump()


@app.put("/sessions/{session_id}/latex")
async def put_session_latex(session_id: str, req: LatexPutRequest):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    raw = req.latex_code or ""
    soft, compat_notes = soften_latex_for_tectonic(raw)
    latex = ensure_full_document(soft)
    log.info(
        "session.latex.step: id=%s chars=%s has_doc=%s compat=%s",
        session_id,
        len(latex),
        "\\begin{document}" in latex,
        compat_notes,
    )
    # Re-sync zone JSON when a full document is saved from the editor
    if "\\begin{document}" in latex:
        try:
            doc = latex_to_zones(latex, source_url=session.source_url)
            sync_session_from_document(session, doc)
            session_store.save(session)
            log.info(
                "session.latex.step: re-zoned order=%s", doc.zone_order
            )
        except Exception as e:
            log.exception(
                "session.latex.error: re-zone failed, saving latex only - %s",
                e,
            )
            session = session_store.set_latex(session, latex)
    else:
        session = session_store.set_latex(session, latex)
    return {
        "session_id": session.session_id,
        "updated_at": session.updated_at,
        "latex_code": session.latex_code,
        "compat_notes": compat_notes,
    }


@app.post("/chat")
async def chat(
    req: ChatRequest,
    authorization: Optional[str] = Header(default=None),
):
    session = session_store.get(req.session_id)
    if not session:
        log.error("chat: session not found id=%s", req.session_id)
        raise HTTPException(status_code=404, detail="Session not found")

    if req.template_name:
        session.template_name = req.template_name

    provider, model = _resolve_llm(req.provider, req.model, session)
    api_key = _resolve_api_key(
        provider=provider,
        request_key=req.api_key,
        authorization=authorization,
    )
    log.info(
        "chat: session=%s provider=%s model=%s api_key=%s msg_chars=%s template=%s",
        req.session_id,
        provider,
        model,
        _mask_key(api_key),
        len(req.message or ""),
        session.template_name,
    )

    try:
        llm_router.get_provider(provider, api_key=api_key)
    except ValueError as e:
        detail = (
            f"{e}. Log in and save your {provider} key in Profile, "
            f"or set the env var for '{provider}'."
        )
        log.error("chat: provider config error - %s", detail)
        raise HTTPException(status_code=400, detail=detail)

    template = template_manager.get_template(session.template_name) or ""

    # Ensure numbered zone document exists (migrate old sessions on the fly)
    doc = document_from_session(session)
    if doc is None or not doc.zones:
        log.info("chat.step: migrate session latex → zones")
        try:
            doc = latex_to_zones(
                session.latex_code or template,
                source_url=session.source_url,
            )
            sync_session_from_document(session, doc)
            session_store.save(session)
        except Exception as e:
            log.exception("chat.error: zone migrate failed - %s", e)
            raise HTTPException(
                status_code=500, detail=f"Zone migrate failed: {e}"
            )

    user_turns = sum(1 for m in session.messages if m.role == "user")
    placeholders = any(
        "[[" in (z.get("latex") or "") for z in (session.zones or [])
    )
    is_first_fill = user_turns == 0 or placeholders
    log.info(
        "chat.step: first_fill=%s user_turns=%s latex_chars=%s zones=%s",
        is_first_fill,
        user_turns,
        len(session.latex_code or ""),
        session.zone_order,
    )

    session_store.append_message(
        session, role="user", content=req.message
    )
    session = session_store.get(req.session_id)

    if session.title == "New resume chat" and req.message.strip():
        session.title = req.message.strip()[:80]
        session_store.save(session)

    history = [m.model_dump() for m in session.messages[:-1]]

    try:
        # Persist a rollback snapshot before the orchestrator edits any zone.
        # If the resulting LaTeX fails to compile, rollback_to_snapshot()
        # restores the last-good state automatically.
        take_snapshot(session, session_store)
        log.info("chat.step: run_chat_turn …")
        result = ai_agent.run_chat_turn(
            user_message=req.message,
            latex_code=session.latex_code,
            template_latex=template,
            history=history,
            provider=provider,
            model=model,
            api_key=api_key,
            is_first_fill=is_first_fill,
            session=session,
        )
        log.info(
            "chat.step: agent done route=%s zones_changed=%s reply_chars=%s",
            result.route,
            result.zones_changed,
            len(result.reply or ""),
        )
    except Exception as e:
        err = str(e)
        log.exception("chat.error: agent failed - %s", e)
        if "invalid_api_key" in err.lower() or "invalid api key" in err.lower() or "401" in err:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Invalid {provider} API key. Open Profile → API keys, "
                    f"paste a fresh key from the provider console, then Save."
                ),
            )
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    pdf_b64 = None
    final_latex = result.latex_code
    if result.zone_document:
        try:
            doc = ZoneDocument(**result.zone_document)
            sync_session_from_document(session, doc)
            final_latex = session.latex_code
            log.info("chat.step: synced zone document zones=%s", session.zone_order)
        except Exception as e:
            log.exception("chat.error: sync zone document failed - %s", e)

    if result.zones_changed or (is_first_fill and result.route == "orchestrator"):
        log.info("chat.step: compile after zone changes …")
        try:
            pdf_bytes, final_latex = compile_with_retry(
                final_latex,
                provider=provider,
                model=model,
                api_key=api_key,
                project_dir=getattr(session, "project_dir", None),
            )
            pdf_b64 = _pdf_b64(pdf_bytes)
            log.info("chat.step: compile ok pdf_bytes=%s", len(pdf_bytes))
            # Keep assembled latex if compile fixer rewrote full doc
            session.latex_code = final_latex
        except Exception as e:
            log.exception("chat.error: compile failed - %s", e)
            # Roll back to last-good snapshot so the session stays valid
            rolled = rollback_to_snapshot(session, session_store)
            if rolled:
                log.info(
                    "chat.step: rolled back to snapshot after compile failure"
                )
                final_latex = session.latex_code
                result.reply = (
                    f"{result.reply}\n\n"
                    "(The edit could not compile — your previous resume "
                    "has been restored. Please rephrase your request.)"
                )
            else:
                result.reply = f"{result.reply}\n\n(Compile issue: {e})"

    session.active_provider = result.provider
    session.active_model = result.model
    session_store.save(session)

    proposal_payload = None
    if result.proposals:
        prop_id = str(uuid.uuid4())
        variants = [
            DraftVariant(
                id=v.id,
                latex_code=v.latex_code,
                summary=v.summary,
                intent=v.intent,
                zone_id=getattr(v, "zone_id", None),
            )
            for v in result.proposals
        ]
        refinement_manager.create_session(prop_id, final_latex, variants)
        proposal_payload = {
            "session_id": prop_id,
            "variants": [v.model_dump() for v in result.proposals],
        }

    meta: Dict[str, Any] = {
        "zones_changed": result.zones_changed,
        "tool_trace": result.tool_trace,
        "route": result.route,
    }
    if proposal_payload:
        meta["proposals"] = proposal_payload

    session_store.append_message(
        session,
        role="assistant",
        content=result.reply,
        provider=result.provider,
        model=result.model,
        meta=meta,
    )
    session = session_store.get(req.session_id)

    return {
        "session": session.model_dump(),
        "reply": result.reply,
        "latex_code": session.latex_code,
        "pdf_base64": pdf_b64,
        "zones_changed": result.zones_changed,
        "proposals": proposal_payload,
        "provider": result.provider,
        "model": result.model,
        "tool_trace": result.tool_trace,
        "route": result.route,
        "catalog": [
            {
                "zone_no": z.get("zone_no"),
                "description": z.get("description"),
                "kind": z.get("kind"),
            }
            for z in (session.zones or [])
        ],
    }


@app.post("/chat/apply")
async def chat_apply_proposal(
    req: ApplyChatProposalRequest,
    authorization: Optional[str] = Header(default=None),
):
    session = session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    provider, model = _resolve_llm(req.provider, req.model, session)
    api_key = _resolve_api_key(
        provider=provider,
        request_key=req.api_key,
        authorization=authorization,
    )
    variant = refinement_manager.get_variant(
        req.proposal_session_id, req.variant_id
    )
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    latex = session.latex_code
    zones = zone_engine.list_zones(latex)
    is_fragment = "\\documentclass" not in (variant.latex_code or "")
    zone_id = variant.zone_id if variant.zone_id in zones else None
    applied = False

    if is_fragment:
        if zone_id is None and zones:
            zone_id = "EXPERIENCE" if "EXPERIENCE" in zones else zones[0]
        if zone_id:
            try:
                latex = zone_engine.replace_zone(
                    latex, zone_id, variant.latex_code
                )
                applied = True
            except Exception as e:
                log.error(
                    "chat/apply: zone replace failed zone=%s - %s",
                    zone_id,
                    e,
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not apply fragment to zone '{zone_id}': {e}",
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="Cannot apply zone fragment: no zones in document",
            )
    else:
        latex = variant.latex_code
        applied = True
        zone_id = None

    compile_error = None
    pdf_b64 = None
    if getattr(session, "template_name", None) == "classic":
        compile_error = (
            "Template 'classic' (moderncv) often fails under Tectonic on "
            "Windows. Start a new chat with the 'modern' template."
        )
        log.warning("chat/apply: classic template compile warning")

    try:
        pdf_bytes, latex = compile_with_retry(
            latex,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        pdf_b64 = _pdf_b64(pdf_bytes)
        compile_error = None
        log.info("chat/apply: compile ok pdf_bytes=%s", len(pdf_bytes))
    except Exception as e:
        log.error("chat/apply: compile failed - %s", e)
        if hasattr(e, "logs") and e.logs:
            log.error("chat/apply: tectonic logs:\n%s", e.logs[:2000])
        compile_error = str(e)
        if getattr(session, "template_name", None) == "classic":
            compile_error = (
                f"{compile_error}. Tip: classic/moderncv is unreliable with "
                "this Tectonic build — use a new chat with template 'modern'."
            )

    note = f"Applied variant: {variant.summary}"
    if compile_error:
        note = f"{note}\n\n(Compile issue: {compile_error})"

    session.latex_code = latex
    session_store.append_message(
        session,
        role="assistant",
        content=note,
        provider=provider,
        model=model,
        meta={
            "zones_changed": [zone_id] if zone_id and applied else [],
            "compile_error": compile_error,
        },
    )
    session = session_store.set_latex(
        session_store.get(req.session_id), latex
    )
    return {
        "session": session.model_dump(),
        "latex_code": latex,
        "pdf_base64": pdf_b64,
        "summary": variant.summary,
        "compile_error": compile_error,
        "zone_id": zone_id,
    }


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    log.info("Starting Resume Maker backend on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
