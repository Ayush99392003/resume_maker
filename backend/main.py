"""AI LaTeX Resume Maker API."""

from __future__ import annotations

import base64
import traceback
import uuid
from typing import Any, Dict, List, Optional

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
    from core.session_store import session_store
    from core.zones import zone_engine
    from core.logging_setup import get_logger, setup_logging
    from core.auth_store import auth_store
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
    from .core.session_store import session_store
    from .core.zones import zone_engine
    from .core.logging_setup import get_logger, setup_logging
    from .core.auth_store import auth_store
    from .core import config
    from .llm_router import llm_router, SUPPORTED_PROVIDERS

setup_logging()
log = get_logger("api")


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
    log.error(
        "Unhandled %s on %s %s: %s\n%s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc,
        traceback.format_exc(),
    )
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


class CreateSessionRequest(BaseModel):
    template_name: str = "modern"
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


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
) -> tuple:
    """Compile LaTeX; on failure ask the agent to fix. Returns (pdf_bytes, latex)."""
    current_latex = latex_code
    last_error = ""

    for attempt in range(max_retries + 1):
        try:
            return compiler.compile(current_latex), current_latex
        except CompilationError as e:
            if attempt == max_retries:
                raise e
            last_error = e.logs
            fix_update = ai_agent.fix_latex_error(
                current_latex,
                last_error,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            current_latex = fix_update.latex_code

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
    log.info("compile: latex_chars=%s", len(req.latex_code or ""))
    try:
        pdf_bytes = compiler.compile(req.latex_code)
        log.info("compile: ok pdf_bytes=%s", len(pdf_bytes))
        return {"pdf_base64": _pdf_b64(pdf_bytes)}
    except CompilationError as e:
        log.error("compile: tectonic failed - %s\n%s", e.message, e.logs[:2000])
        raise HTTPException(
            status_code=500,
            detail=f"Tectonic failed: {e.message}. {e.logs[:500]}",
        )
    except Exception as e:
        log.exception("compile: unexpected error")
        raise HTTPException(status_code=500, detail=str(e))


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
        zones = zone_engine.list_zones(latex)
        sections = sectional_parser.extract_sections(latex)
        return {
            "sections": list(sections.keys()),
            "zones": zones,
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


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    provider = req.provider or config.LLM_PROVIDER
    model = req.model or config.MODEL_NAME
    template = template_manager.get_template(req.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    session = session_store.create(
        template_name=req.template_name,
        title=req.title or "New resume chat",
        latex_code=template,
        provider=provider,
        model=model,
        welcome=(
            "Welcome! Paste your bio or career summary to build a LaTeX resume. "
            "You can switch models anytime - chat history is kept."
        ),
    )
    return session.model_dump()


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
    session = session_store.set_latex(session, req.latex_code)
    return {"session_id": session.session_id, "updated_at": session.updated_at}


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

    template = template_manager.get_template(session.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Count prior user messages to detect first fill
    user_turns = sum(1 for m in session.messages if m.role == "user")
    is_first_fill = user_turns == 0 or not session.latex_code.strip() or (
        session.latex_code.strip() == template.strip()
    )
    log.info(
        "chat: first_fill=%s user_turns=%s latex_chars=%s zones=%s",
        is_first_fill,
        user_turns,
        len(session.latex_code or ""),
        zone_engine.list_zones(session.latex_code or template),
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
        result = ai_agent.run_chat_turn(
            user_message=req.message,
            latex_code=session.latex_code if not is_first_fill else "",
            template_latex=template,
            history=history,
            provider=provider,
            model=model,
            api_key=api_key,
            is_first_fill=is_first_fill,
        )
        log.info(
            "chat: agent ok zones_changed=%s proposals=%s reply_chars=%s",
            result.zones_changed,
            bool(result.proposals),
            len(result.reply or ""),
        )
    except Exception as e:
        err = str(e)
        log.exception("chat: agent failed - %s", e)
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
    if result.zones_changed or is_first_fill:
        try:
            pdf_bytes, final_latex = compile_with_retry(
                result.latex_code,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            pdf_b64 = _pdf_b64(pdf_bytes)
            log.info("chat: compile ok pdf_bytes=%s", len(pdf_bytes))
        except Exception as e:
            log.error("chat: compile failed - %s", e)
            # Still save latex; report compile issue in reply
            result.reply = (
                f"{result.reply}\n\n(Compile issue: {e})"
            )

    session.latex_code = final_latex
    session.active_provider = result.provider
    session.active_model = result.model

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
        "latex_code": final_latex,
        "pdf_base64": pdf_b64,
        "zones_changed": result.zones_changed,
        "proposals": proposal_payload,
        "provider": result.provider,
        "model": result.model,
        "tool_trace": result.tool_trace,
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
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
