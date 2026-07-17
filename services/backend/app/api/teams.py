"""Teams CRUD (manual assignment; auto-routing lands in R4)."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.api._ids import parse_uuid
from app.compat import Ctx, method
from app.models import Team, TeamMember, User, WorkspaceMember
from app.models.inbox import ROUTING_MODES
from app.tenancy import active_workspace, require_manager


def _get_checked(ctx: Ctx, team: str) -> Team:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Team, uuid.UUID(team))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Team not found in this workspace")
    return row


def _serialize(ctx: Ctx, team: Team) -> dict:
    members = ctx.db.execute(
        select(User).join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team.id)
    ).scalars()
    return {
        "name": str(team.id),
        "team_name": team.team_name,
        "routing": team.routing,
        "capacity_per_agent": team.capacity_per_agent,
        "members": [str(u.id) for u in members],
    }


def _set_members(ctx: Ctx, team: Team, member_ids: list) -> None:
    ctx.db.query(TeamMember).filter(TeamMember.team_id == team.id).delete()
    # Only users who belong to THIS workspace may be team members — otherwise a
    # manager could seed a team with foreign user ids (which would then surface
    # in the roster and be assignable).
    valid = set(ctx.db.execute(
        select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == team.workspace_id
        )
    ).scalars())
    for mid in member_ids or []:
        uid = parse_uuid(mid, "member id")
        if uid not in valid:
            raise HTTPException(400, "Team members must belong to this workspace")
        ctx.db.add(TeamMember(team_id=team.id, user_id=uid))


@method("wavedesk.api.teams.list_teams")
def list_teams(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(Team).where(Team.workspace_id == ws.id).order_by(Team.team_name)
    ).scalars()
    return [_serialize(ctx, t) for t in rows]


@method("wavedesk.api.teams.create_team")
def create_team(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    name = (ctx.params.get("team_name") or "").strip()
    if not name:
        raise HTTPException(400, "team_name is required")
    routing = ctx.params.get("routing") or "manual"
    if routing not in ROUTING_MODES:
        raise HTTPException(400, f"Invalid routing mode: {routing}")
    team = Team(
        workspace_id=ws.id,
        team_name=name,
        routing=routing,
        capacity_per_agent=int(ctx.params.get("capacity_per_agent") or 0),
    )
    ctx.db.add(team)
    ctx.db.flush()
    _set_members(ctx, team, ctx.params.get("members") or [])
    return _serialize(ctx, team)


@method("wavedesk.api.teams.update_team")
def update_team(ctx: Ctx) -> dict:
    team = _get_checked(ctx, ctx.params.get("team") or "")
    require_manager(ctx, team.workspace_id)
    if ctx.params.get("team_name") is not None:
        team.team_name = ctx.params["team_name"].strip()
    if ctx.params.get("routing") is not None:
        if ctx.params["routing"] not in ROUTING_MODES:
            raise HTTPException(400, f"Invalid routing mode: {ctx.params['routing']}")
        team.routing = ctx.params["routing"]
    if ctx.params.get("capacity_per_agent") is not None:
        team.capacity_per_agent = int(ctx.params["capacity_per_agent"])
    if ctx.params.get("members") is not None:
        _set_members(ctx, team, ctx.params["members"])
    return _serialize(ctx, team)


@method("wavedesk.api.teams.delete_team")
def delete_team(ctx: Ctx) -> dict:
    team = _get_checked(ctx, ctx.params.get("team") or "")
    require_manager(ctx, team.workspace_id)
    name = str(team.id)
    ctx.db.delete(team)
    return {"deleted": name}
