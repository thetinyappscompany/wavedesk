"""AI + media API surface — settings/usage (leak-guarded), BYOK, kill switch,
copilot, agent config + knowledge, flag rules, media URL."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import copilot, crypto
from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.gating import has_feature
from app.models import (
    AiAgentConfig,
    AiFlagRule,
    KnowledgeDoc,
    Message,
    PricingConfig,
    Subscription,
)
from app.tenancy import active_workspace, require_manager


def _require_addon(ctx: Ctx, ws) -> None:
    if not has_feature(ctx.db, ws.id, "ai_addon"):
        raise HTTPException(403, "This feature requires the AI add-on.")


def _sub(ctx: Ctx, ws) -> Subscription:
    from app.gating import ensure_subscription

    return ensure_subscription(ctx.db, ws.id)


# --- settings + usage (NEVER leak confidential pricing — #4) ------------------


@method("wavedesk.api.ai.ai_settings")
def ai_settings(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    sub = _sub(ctx, ws)
    return {
        "ai_addon": has_feature(ctx.db, ws.id, "ai_addon"),
        "kill_switch": bool((sub.addons or {}).get("ai_kill_switch")),
        "byok_set": bool((sub.addons or {}).get("byok_key_encrypted")),
    }


@method("wavedesk.api.ai.usage_meter")
def usage_meter(ctx: Ctx) -> dict:
    """Friendly meter — allowance % + credits ₹ ONLY. Never tokens/USD/rates."""
    from app import wallet
    from app.ai import metering

    ws = active_workspace(ctx)
    cfg = ctx.db.execute(select(PricingConfig)).scalar_one_or_none()
    allowance = cfg.allowance_usd if cfg else 5.0
    consumed = metering.consumed_usd(ctx.db, ws.id, metering.current_period())
    pct = min(100, round(consumed / allowance * 100)) if allowance else 0
    return {
        "allowance_used_pct": pct,
        "credits_balance_inr": wallet.get_balance(ctx.db, ws.id),
    }


@method("wavedesk.api.ai.set_byok")
def set_byok(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    key = (ctx.params.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "key is required")
    sub = _sub(ctx, ws)
    addons = dict(sub.addons or {})
    addons["byok_key_encrypted"] = crypto.encrypt(key)
    sub.addons = addons
    return {"byok_set": True}


@method("wavedesk.api.ai.revoke_byok")
def revoke_byok(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    sub = _sub(ctx, ws)
    addons = dict(sub.addons or {})
    addons.pop("byok_key_encrypted", None)
    sub.addons = addons
    return {"byok_set": False}


@method("wavedesk.api.ai.set_kill_switch")
def set_kill_switch(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    sub = _sub(ctx, ws)
    addons = dict(sub.addons or {})
    addons["ai_kill_switch"] = bool(ctx.params.get("enabled"))
    sub.addons = addons
    return {"kill_switch": addons["ai_kill_switch"]}


# --- copilot ------------------------------------------------------------------


def _chat_transcript(ctx: Ctx, chat) -> str:
    rows = ctx.db.execute(
        select(Message).where(Message.chat_id == chat.id)
        .order_by(Message.created_at.desc()).limit(20)
    ).scalars().all()
    rows.reverse()
    return "\n".join(f"{m.direction}: {m.body or ''}" for m in rows)


@method("wavedesk.api.copilot.suggest_reply")
def copilot_suggest(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    _require_addon(ctx, ws)
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    return {"text": copilot.suggest_reply(ctx.db, ws.id, _chat_transcript(ctx, chat))}


@method("wavedesk.api.copilot.rewrite")
def copilot_rewrite(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    _require_addon(ctx, ws)
    return {"text": copilot.rewrite(
        ctx.db, ws.id, ctx.params.get("text") or "", ctx.params.get("mode") or "polish"
    )}


@method("wavedesk.api.copilot.translate")
def copilot_translate(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    _require_addon(ctx, ws)
    return {"text": copilot.translate(
        ctx.db, ws.id, ctx.params.get("text") or "", ctx.params.get("target") or "English"
    )}


@method("wavedesk.api.copilot.summarize")
def copilot_summarize(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    _require_addon(ctx, ws)
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    return {"text": copilot.summarize(ctx.db, ws.id, _chat_transcript(ctx, chat))}


# --- agent config + knowledge -------------------------------------------------


def _agent_cfg(ctx: Ctx, ws) -> AiAgentConfig:
    cfg = ctx.db.execute(
        select(AiAgentConfig).where(AiAgentConfig.workspace_id == ws.id)
    ).scalar_one_or_none()
    if cfg is None:
        cfg = AiAgentConfig(workspace_id=ws.id)
        ctx.db.add(cfg)
        ctx.db.flush()
    return cfg


@method("wavedesk.api.agent.get_agent_config")
def get_agent_config(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    cfg = _agent_cfg(ctx, ws)
    return {
        "enabled": bool(cfg.enabled), "persona_prompt": cfg.persona_prompt,
        "confidence_threshold": cfg.confidence_threshold,
        "handoff_team": str(cfg.handoff_team_id) if cfg.handoff_team_id else None,
        "after_hours_only": bool(cfg.after_hours_only), "auto_ticket": bool(cfg.auto_ticket),
    }


@method("wavedesk.api.agent.update_agent_config")
def update_agent_config(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    cfg = _agent_cfg(ctx, ws)
    if "enabled" in ctx.params:
        cfg.enabled = bool(ctx.params["enabled"])
    if ctx.params.get("persona_prompt") is not None:
        cfg.persona_prompt = ctx.params["persona_prompt"]
    if ctx.params.get("confidence_threshold") is not None:
        cfg.confidence_threshold = float(ctx.params["confidence_threshold"])
    if "auto_ticket" in ctx.params:
        cfg.auto_ticket = bool(ctx.params["auto_ticket"])
    if "after_hours_only" in ctx.params:
        cfg.after_hours_only = bool(ctx.params["after_hours_only"])
    if ctx.params.get("handoff_team"):
        cfg.handoff_team_id = uuid.UUID(ctx.params["handoff_team"])
    return get_agent_config(ctx)


@method("wavedesk.api.agent.list_knowledge")
def list_knowledge(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.workspace_id == ws.id)
    ).scalars()
    return [{"name": str(d.id), "title": d.title, "status": d.status} for d in rows]


@method("wavedesk.api.agent.create_knowledge")
def create_knowledge(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    doc = KnowledgeDoc(
        workspace_id=ws.id,
        title=(ctx.params.get("title") or "Untitled").strip(),
        content=ctx.params.get("content") or "",
    )
    ctx.db.add(doc)
    ctx.db.flush()
    from app import tasks

    tasks.enqueue(_ingest_doc, workspace_id=str(ws.id), doc_id=str(doc.id))
    return {"name": str(doc.id), "status": doc.status}


def _ingest_doc(workspace_id: str, doc_id: str) -> None:
    from app.ai import rag
    from app.db import get_sessionmaker

    db = get_sessionmaker()()
    try:
        doc = db.get(KnowledgeDoc, uuid.UUID(doc_id))
        if doc is None:
            return
        try:
            rag.index_doc(workspace_id, doc_id, doc.content)
            doc.status = "indexed"
        except Exception:  # noqa: BLE001
            doc.status = "failed"
        db.commit()
    finally:
        db.close()


@method("wavedesk.api.agent.delete_knowledge")
def delete_knowledge(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        doc = ctx.db.get(KnowledgeDoc, uuid.UUID(ctx.params.get("knowledge") or ""))
    except ValueError:
        doc = None
    if doc is None or doc.workspace_id != ws.id:
        raise HTTPException(404, "Knowledge doc not found")
    from app.ai import rag

    try:
        rag.delete_doc(ws.id, str(doc.id))
    except Exception:  # noqa: BLE001
        pass
    name = str(doc.id)
    ctx.db.delete(doc)
    return {"deleted": name}


@method("wavedesk.api.agent.preview_answer")
def preview_answer(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    _require_addon(ctx, ws)
    from app.ai import agent as ai_agent

    return ai_agent.answer(ctx.db, ws.id, ctx.params.get("question") or "")


# --- flag rules ---------------------------------------------------------------


def _flag_out(r: AiFlagRule) -> dict:
    return {
        "name": str(r.id), "flag_key": r.flag_key, "label": r.label, "prompt": r.prompt,
        "action": r.action, "priority": r.priority, "enabled": bool(r.enabled),
    }


@method("wavedesk.api.flagging.list_rules")
def flag_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(AiFlagRule).where(AiFlagRule.workspace_id == ws.id)
    ).scalars()
    return [_flag_out(r) for r in rows]


@method("wavedesk.api.flagging.create_rule")
def flag_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    row = AiFlagRule(
        workspace_id=ws.id,
        flag_key=(ctx.params.get("flag_key") or "flag").strip(),
        label=ctx.params.get("label"),
        prompt=ctx.params.get("prompt") or "",
        action=ctx.params.get("action") or "flag",
        priority=ctx.params.get("priority") or "medium",
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _flag_out(row)


@method("wavedesk.api.flagging.update_rule")
def flag_update(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(AiFlagRule, uuid.UUID(ctx.params.get("rule") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found")
    for key in ("flag_key", "label", "prompt", "action", "priority"):
        if ctx.params.get(key) is not None:
            setattr(row, key, ctx.params[key])
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    return _flag_out(row)


@method("wavedesk.api.flagging.delete_rule")
def flag_delete(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(AiFlagRule, uuid.UUID(ctx.params.get("rule") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found")
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


# --- media --------------------------------------------------------------------


@method("wavedesk.api.media.media_url")
def media_url(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    from app import media_store

    try:
        msg = ctx.db.get(Message, uuid.UUID(ctx.params.get("message") or ""))
    except ValueError:
        msg = None
    if msg is None or msg.workspace_id != ws.id:
        raise HTTPException(404, "Message not found")
    if not msg.media_key:
        raise HTTPException(404, "Message has no media")
    return {"url": media_store.presigned_url(msg.media_key), "mimetype": msg.media_mimetype}
