"""ROADMAP invariant 10, as a test rather than a promise: everything the
panel can propose is reachable through the structured interface with
the panel closed, and reaching it that way lands the same rows and the
same action-log entries.

Each case does the same change twice in two projects -- once by calling
the endpoint the form calls, once by applying what the panel proposed --
and compares what the database holds afterwards."""

import uuid

from sqlalchemy import select

from app.assistant import propose
from app.assistant.models import ConversationMessage
from app.assistant.schemas import ScreenIn
from app.engine.conversation import Route, RouteTargets
from app.plan import service as plan_service
from app.takeoff.models import (
    Action, Document, Item, Note, Project, ReviewStatus, ScopeStatement, Sheet,
)

SPEC_TEXT = "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\nPhase 2 work follows.\n"


# --- fixture factory: two equivalent projects, same org --------------


def _project(db, org, name):
    p = Project(org_id=org.id, name=name, revision_set_label="")
    db.add(p); db.flush(); return p


def _sheet(db, project, number="E2.1", **over):
    fields = dict(project_id=project.id, number=number, title="Power plan", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    fields.update(over)
    s = Sheet(**fields)
    db.add(s); db.flush(); return s


def _item(db, project, sheet, **over):
    fields = dict(project_id=project.id, sheet_id=sheet.id, symbol="luminaire", name="Unclassified symbol",
                  system="Unknown", category="Unclassified", quantity=1, unit="EA",
                  status=ReviewStatus.ATTENTION, source_tag="F")
    fields.update(over)
    i = Item(**fields)
    db.add(i); db.flush(); return i


def _doc(db, project, dana, filename, doc_type, **over):
    fields = dict(project_id=project.id, filename=filename, doc_type=doc_type, content_type="application/pdf",
                  size_bytes=1, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id,
                  status="processed", context_text="", page_count=1)
    fields.update(over)
    d = Document(**fields)
    db.add(d); db.flush(); return d


def _plan_sheet(db, project, doc, **over):
    fields = dict(project_id=project.id, number="E2.1", title="Power plan", discipline="Electrical", revision="",
                  scale='1/8" = 1\'-0"', scale_options=[], plan="", takeoff_id=str(doc.id), page_index=0,
                  kind="plan", unreadable_reason="", schedule_text="")
    fields.update(over)
    s = Sheet(**fields)
    db.add(s); db.flush(); return s


def _scope(db, project, doc, **over):
    fields = dict(org_id=project.org_id, project_id=project.id, document_id=doc.id, page_index=1, kind="excluded",
                  text="Site lighting.", quote="- Site lighting.", status="found", run_id=uuid.uuid4())
    fields.update(over)
    s = ScopeStatement(**fields)
    db.add(s); db.flush(); return s


def _seed(db, org, dana, name):
    """One project carrying everything the five proposal kinds need: a
    sheet with a two-row cluster (item), a scope statement (scope), a
    processed spec plus a drawing set with a schedule sheet, a
    phase-bearing sheet and a scaleless plan sheet (plan_line via the
    spec section, plan_answer via the no-scale question)."""
    project = _project(db, org, name)
    sheet = _sheet(db, project)
    anchor = _item(db, project, sheet, name="Item A")
    twin = _item(db, project, sheet, name="Item A")

    spec_doc = _doc(db, project, dana, "Spec.pdf", "Specifications", context_text=SPEC_TEXT)
    drawings = _doc(db, project, dana, "E-set.pdf", "Drawings", page_count=3)
    _plan_sheet(db, project, drawings, number="E0.1", title="Luminaire schedule", kind="schedule", page_index=0, scale="")
    _plan_sheet(db, project, drawings, number="E2.1", title="Phase 1 power plan", page_index=1)
    no_scale_sheet = _plan_sheet(db, project, drawings, number="E2.2", title="Lighting plan", page_index=2, scale="")

    scope_statement = _scope(db, project, drawings)

    return dict(project=project, sheet=sheet, anchor=anchor, twin=twin, spec_doc=spec_doc,
               drawings=drawings, no_scale_sheet=no_scale_sheet, scope_statement=scope_statement)


def _screen(**over):
    fields = dict(name="takeoff")
    fields.update(over)
    return ScreenIn(**fields)


def _route(intent, form="selection", **kw):
    return Route(intent=intent,
                targets=RouteTargets(form=form, tag=kw.pop("tag", ""), record_key=kw.pop("record_key", "")),
                field=kw.pop("field", ""), value=kw.pop("value", ""))


def _actions_kind_label(db, project_id):
    rows = db.scalars(select(Action).where(Action.project_id == project_id).order_by(Action.seq)).all()
    return [(a.kind, a.label) for a in rows]


def _conversation_rows(db, project_id):
    return db.scalars(select(ConversationMessage).where(ConversationMessage.project_id == project_id)).all()


# --- item: reclassify --------------------------------------------------


def test_item_reclassify_reaches_the_same_end_state_through_apply_proposal(db, org, dana, signed_in_user, client):
    """Form path: the item panel's own flow -- POST /resolve, then POST
    /apply-proposal with the returned proposal and the estimator's
    sentence as the note (docs/specs/say-what-it-is.md; DecisionArea
    always sends the sentence as `note`, never null).

    Panel path: propose.build with a hand-made reclassify Route (no
    model call -- resolve_for_item falls back to the typed reading with
    no ANTHROPIC_API_KEY in this process), then apply-proposal with the
    body applyProposal.js's `item` arm actually sends -- which is
    `note: null`, always, for every item-kind card."""
    form_env = _seed(db, org, dana, "Form project — item")
    panel_env = _seed(db, org, dana, "Panel project — item")
    db.commit()

    message = "these are all 2x4 LED troffers, type F"

    # Form path.
    resolved = client.post(f"/api/items/{form_env['anchor'].id}/resolve",
                           json={"text": message, "cluster": True})
    assert resolved.status_code == 200, resolved.text
    form_apply = client.post(f"/api/items/{form_env['anchor'].id}/apply-proposal",
                             json={"proposal": resolved.json(), "approve": False, "note": message})
    assert form_apply.status_code == 200, form_apply.text

    # Panel path: propose.build, by hand, then applyProposal.js's own body.
    route = _route("reclassify", field="classification")
    screen = _screen(sheet_id=panel_env["sheet"].id, item_id=panel_env["anchor"].id)
    built = propose.build(db, project=panel_env["project"], route=route, screen=screen, message=message)
    assert built is not None and built["kind"] == "item"
    # applyProposal.js: store.applyProposal(proposal.itemId, mapProposal(proposal.proposal),
    # { approve: false, note: null }) -- mapProposal -> proposalToWire round-trips the
    # inner (already snake_case) proposal dict back to the identical wire shape.
    panel_apply = client.post(f"/api/items/{built['item_id']}/apply-proposal",
                              json={"proposal": built["proposal"], "approve": False, "note": None})
    assert panel_apply.status_code == 200, panel_apply.text

    db.expire_all()
    for form_item, panel_item in ((form_env["anchor"], panel_env["anchor"]), (form_env["twin"], panel_env["twin"])):
        f, p = db.get(Item, form_item.id), db.get(Item, panel_item.id)
        assert (f.name, f.system, f.category, float(f.quantity), f.status, f.resolve_note) == \
               (p.name, p.system, p.category, float(p.quantity), p.status, p.resolve_note)

    assert _actions_kind_label(db, form_env["project"].id) == _actions_kind_label(db, panel_env["project"].id)
    assert _conversation_rows(db, panel_env["project"].id) == []


# --- note: set_context --------------------------------------------------


def test_a_context_note_reaches_the_same_end_state_through_post_notes(db, org, dana, signed_in_user, client):
    """Form path: NoteForm's own POST to /projects/{id}/notes.
    Panel path: propose.build with a hand-made set_context Route, then
    applyProposal.js's `note` arm -- store.createNote with a fixed
    scope/status/usage, the proposal's own title/body/category."""
    form_env = _seed(db, org, dana, "Form project — note")
    panel_env = _seed(db, org, dana, "Panel project — note")
    db.commit()

    message = "Ceiling is 14 feet in the warehouse."
    route = _route("set_context", form="none", field="text", value=message)

    form_built = propose.build(db, project=form_env["project"], route=route, screen=_screen(), message=message)
    panel_built = propose.build(db, project=panel_env["project"], route=route, screen=_screen(), message=message)
    assert form_built["kind"] == panel_built["kind"] == "note"
    assert (form_built["title"], form_built["body"], form_built["category"]) == \
           (panel_built["title"], panel_built["body"], panel_built["category"])

    def _note_body(built):
        return {"scope": "project", "scope_ref": None, "title": built["title"], "body": built["body"],
                "category": built["category"], "status": "open", "rfi_needed": False, "usage": "context",
                "source_ref": "", "obsolete_after_revision": ""}

    form_resp = client.post(f"/api/projects/{form_env['project'].id}/notes", json=_note_body(form_built))
    assert form_resp.status_code == 201, form_resp.text
    panel_resp = client.post(f"/api/projects/{panel_env['project'].id}/notes", json=_note_body(panel_built))
    assert panel_resp.status_code == 201, panel_resp.text

    db.expire_all()
    form_note = db.get(Note, uuid.UUID(form_resp.json()["id"]))
    panel_note = db.get(Note, uuid.UUID(panel_resp.json()["id"]))
    tracked = ("scope", "scope_ref", "title", "body", "category", "status", "rfi_needed", "usage",
              "source_ref", "obsolete_after_revision")
    assert [getattr(form_note, f) for f in tracked] == [getattr(panel_note, f) for f in tracked]

    assert _actions_kind_label(db, form_env["project"].id) == _actions_kind_label(db, panel_env["project"].id)
    assert _conversation_rows(db, panel_env["project"].id) == []


# --- scope: decide_scope -------------------------------------------------


def test_a_scope_confirmation_reaches_the_same_end_state_through_patch_scope(db, org, dana, signed_in_user, client):
    """Form path: the confirm screen's own PATCH /scope/{id}.
    Panel path: propose.build with a hand-made decide_scope Route (the
    key the screen itself offers, from record_keys), then the same
    PATCH with applyProposal.js's `scope` arm body."""
    form_env = _seed(db, org, dana, "Form project — scope")
    panel_env = _seed(db, org, dana, "Panel project — scope")
    db.commit()

    message = "site lighting is by others, that's right"
    screen = _screen(name="confirm")

    def _decide(env):
        statement = env["scope_statement"]
        route = _route("decide_scope", form="record", record_key=f"scope:{statement.id}",
                       field="status", value="confirmed")
        built = propose.build(db, project=env["project"], route=route, screen=screen, message=message)
        assert built is not None and built["kind"] == "scope"
        return statement, built

    form_statement, form_built = _decide(form_env)
    panel_statement, panel_built = _decide(panel_env)
    assert form_built["status"] == panel_built["status"] == "confirmed"

    def _scope_body(built):
        return {"status": built["status"]} if built.get("status") is not None else {"edited_text": built["edited_text"]}

    form_resp = client.patch(f"/api/scope/{form_statement.id}", json=_scope_body(form_built))
    assert form_resp.status_code == 200, form_resp.text
    panel_resp = client.patch(f"/api/scope/{panel_statement.id}", json=_scope_body(panel_built))
    assert panel_resp.status_code == 200, panel_resp.text

    db.expire_all()
    form_row = db.get(ScopeStatement, form_statement.id)
    panel_row = db.get(ScopeStatement, panel_statement.id)
    assert (form_row.status, form_row.edited_text) == (panel_row.status, panel_row.edited_text)

    assert _actions_kind_label(db, form_env["project"].id) == _actions_kind_label(db, panel_env["project"].id)
    assert _conversation_rows(db, panel_env["project"].id) == []


# --- plan_line: decide_plan on a derived spec section ---------------------


def _spec_key(db, project):
    _docs, _scope, specs, _scheds, _phases, _added, _questions = plan_service.derive(db, project)
    assert specs, "expected a derived spec section line"
    return specs[0].key


def test_a_plan_line_confirmation_reaches_the_same_end_state_through_patch_plan_lines(
    db, org, dana, signed_in_user, client
):
    """Form path: the plan screen's own PATCH /plan/lines/{key}.
    Panel path: propose.build with a hand-made decide_plan Route naming
    the key record_keys offers, then applyProposal.js's `plan_line` arm."""
    form_env = _seed(db, org, dana, "Form project — plan line")
    panel_env = _seed(db, org, dana, "Panel project — plan line")
    db.commit()

    message = "that spec section applies, confirm it"
    screen = _screen(name="plan")

    def _decide(env):
        entry_key = _spec_key(db, env["project"])
        route = _route("decide_plan", form="record", record_key=f"plan:{entry_key}", field="status", value="confirmed")
        built = propose.build(db, project=env["project"], route=route, screen=screen, message=message)
        assert built is not None and built["kind"] == "plan_line"
        return entry_key, built

    form_key, form_built = _decide(form_env)
    panel_key, panel_built = _decide(panel_env)
    assert form_built["status"] == panel_built["status"] == "confirmed"

    def _line_body(built):
        return {"status": built["status"]} if built.get("status") is not None else {"edited_text": built["edited_text"]}

    form_resp = client.patch(f"/api/projects/{form_env['project'].id}/plan/lines/{form_key}", json=_line_body(form_built))
    assert form_resp.status_code == 200, form_resp.text
    panel_resp = client.patch(f"/api/projects/{panel_env['project'].id}/plan/lines/{panel_key}", json=_line_body(panel_built))
    assert panel_resp.status_code == 200, panel_resp.text

    from app.plan.models import PlanDecision

    form_decision = db.scalars(select(PlanDecision).where(PlanDecision.project_id == form_env["project"].id)).one()
    panel_decision = db.scalars(select(PlanDecision).where(PlanDecision.project_id == panel_env["project"].id)).one()
    assert (form_decision.status, form_decision.edited_text) == (panel_decision.status, panel_decision.edited_text)

    assert _actions_kind_label(db, form_env["project"].id) == _actions_kind_label(db, panel_env["project"].id)
    assert _conversation_rows(db, panel_env["project"].id) == []


# --- plan_answer: decide_plan on a derived question -----------------------


def _question_key(db, project):
    _docs, _scope, _specs, _scheds, _phases, _added, questions = plan_service.derive(db, project)
    assert questions, "expected a derived no-scale question"
    return questions[0].key


def test_a_plan_answer_reaches_the_same_end_state_through_post_plan_answer(db, org, dana, signed_in_user, client):
    """Form path: the plan screen's own POST /plan/questions/{key}/answer.
    Panel path: propose.build with a hand-made decide_plan Route naming
    the question's key, then applyProposal.js's `plan_answer` arm."""
    form_env = _seed(db, org, dana, "Form project — plan answer")
    panel_env = _seed(db, org, dana, "Panel project — plan answer")
    db.commit()

    message = "E2.2 is at the same scale as E2.1 — use 1/8\" = 1'-0\"."
    screen = _screen(name="plan")

    def _decide(env):
        entry_key = _question_key(db, env["project"])
        route = _route("decide_plan", form="record", record_key=f"plan:{entry_key}", field="text", value=message)
        built = propose.build(db, project=env["project"], route=route, screen=screen, message=message)
        assert built is not None and built["kind"] == "plan_answer"
        return entry_key, built

    form_key, form_built = _decide(form_env)
    panel_key, panel_built = _decide(panel_env)
    assert form_built["body"] == panel_built["body"] == message

    form_resp = client.post(f"/api/projects/{form_env['project'].id}/plan/questions/{form_key}/answer",
                            json={"body": form_built["body"]})
    assert form_resp.status_code == 200, form_resp.text
    panel_resp = client.post(f"/api/projects/{panel_env['project'].id}/plan/questions/{panel_key}/answer",
                             json={"body": panel_built["body"]})
    assert panel_resp.status_code == 200, panel_resp.text

    from app.plan.models import PlanDecision

    form_decision = db.scalars(select(PlanDecision).where(PlanDecision.project_id == form_env["project"].id)).one()
    panel_decision = db.scalars(select(PlanDecision).where(PlanDecision.project_id == panel_env["project"].id)).one()
    assert form_decision.status == panel_decision.status == "answered"

    # answer() also writes a Note as a side effect (its own note_add
    # action) -- a second changed record the comparison must not miss.
    form_note = db.get(Note, form_decision.note_id)
    panel_note = db.get(Note, panel_decision.note_id)
    assert (form_note.title, form_note.body, form_note.category, form_note.status) == \
           (panel_note.title, panel_note.body, panel_note.category, panel_note.status)

    assert _actions_kind_label(db, form_env["project"].id) == _actions_kind_label(db, panel_env["project"].id)
    assert _conversation_rows(db, panel_env["project"].id) == []
