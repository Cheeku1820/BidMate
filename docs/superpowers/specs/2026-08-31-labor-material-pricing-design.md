# Labor and Material Pricing workspaces

## Scope

Two new project workspaces — **Labor** and **Material pricing** — currently
listed in `ProjectNav.jsx` as `built: false`. Both are fully specified
already in `docs/superpowers/specs/2026-08-16-bidmate-frontend-product-design.md`
§12–13; this document is the implementation-level design for that spec,
narrowed by decisions made in brainstorming.

**In scope:**
- Real, backend-persisted company-level labor rates and material prices.
- Real, backend-persisted per-item project overrides (hours, crew mix,
  rate, adjustment percent for labor; price for materials).
- A precedence chain for both, with the source always visible.
- Migrating `CompanySettings.jsx`'s "Labor rates," "Labor adjustments,"
  and "Material pricing" tabs off `localStorage` onto that same backend
  data — they currently persist to `bidmate:company-settings`
  (`src/lib/settingsStore.js`), a leftover from the pre-API-only-foundation
  seed era that the seed-store removal never touched because it isn't
  part of the review-workspace store.

**Explicitly out of scope, decided during brainstorming:**
- **Supplier quote / price-sheet upload and matching** (parsing an
  emailed screenshot or a spreadsheet, matching its lines against
  materials, detecting what it didn't cover). This is real
  document-understanding work — the "Pricing agent... lookup, plus a
  quote-line matcher" `CLAUDE.md` already names as a future agent — and
  gets its own spec once this foundation exists. Every precedence tier
  this plan builds is reachable by typing a value in by hand; nothing
  here depends on upload existing.
- **Assemblies** (workspace #6). Material pricing rows in this plan map
  1:1 to an approved takeoff item (fixtures, receptacles, panels).
  Derived materials an assembly would produce (wire footage, conduit
  footage, boxes, fittings) are not represented — there is no takeoff
  item for them today, and building the layer that would explode a
  device into its components is a separate, comparably-sized effort.
- **"Ask BidMate"** (the conversation drawer, §4.4 of the frontend spec).
  Nothing in `src/` implements it, and `CLAUDE.md`'s conversation-panel
  section flags an unresolved doctrine conflict between it and the rest
  of the product spec that a deliberate decision has to resolve before
  it's built at all — not as a side effect of this plan.
- **A reusable, company-wide adjustment-rule library** (the mockup's
  sidebar of saved rules like "Mounting height above 16′: +25%"). Each
  labor row instead gets a typed percentage + reason, applied once.
- **A per-role rate table beyond journeyman/foreman/apprentice**, and any
  crew-mix rate beyond a simple weighted average of those three.
- The rest of `CompanySettings.jsx` (profile, waste/overhead/profit
  markup, export preferences) and all of `ProjectSettings.jsx` stay on
  `localStorage`, unmigrated. Flagged here rather than silently left as
  a known, pre-existing inconsistency this plan does not resolve.

## Why the data model looks the way it does

Three facts from the existing engine drove the shape below, not
invention:

1. **`Item` already carries the engine's original pricing — but only
   some of it is real enough to trust.** `material_cost`, `labor_hours`,
   `labor_cost`, `total_cost` are real columns, populated at ingest
   either by the LLM path (`llm.estimate()`, which prices every item for
   the project's actual location) or, when no key is configured, by the
   deterministic fallback (`catalog.py`'s fixed placeholder labor hours
   and `regions.py`'s ~15-entry hardcoded rate table — both explicitly
   documented as rough guesses, neither sourced from anything published).
   A working MVP that firms bid real work off of cannot present the
   second kind as if it were the first. So this plan tracks which one
   actually ran (`Project.pricing_source`, below) and only treats
   `Item`'s stored cost/hours as a real "baseline" tier when it came from
   the LLM. When it didn't, that tier simply doesn't exist for the
   project — see Precedence resolution.

2. **There is no `Item.catalog_id`.** The deterministic classification
   path resolves a `CatalogItem` internally but never puts its id on the
   wire payload, and the LLM classification path (when a key is present)
   never has one at all — it classifies against schedule text directly,
   with no stable id to key on. Company-level rate/price entries in this
   plan therefore key on **the item's classified name** (`Item.name`,
   e.g. "20A duplex receptacle"), not a catalog id. This is coarser than
   ideal — an LLM-classified item whose wording drifts from a company
   price entry's name won't match — but it fails safe: an unmatched name
   just falls through to the next tier (company price → regional
   baseline), never to a silently wrong price. More precise matching is
   exactly the kind of problem the deferred quote-matching work exists
   to solve properly; this plan does not attempt it.

3. **"NECA" is not something this product can claim.** `catalog.py`'s
   own docstring calls its labor-hour figures "rough
   order-of-magnitude placeholders." The mockup's "NECA Manual of Labor
   Units, 2026 edition · licensed through Mar 2027" is a specific
   commercial license this project does not hold. Every place this
   design surfaces that figure, it is labeled "Catalog default hours" or
   "Company hours," never NECA.

## Tracking which mechanism actually priced a project

`estimate.py`'s payload already carries `source` (`"llm"` or
`"deterministic"`) and `location_note` (a one-sentence basis, e.g. "Rate
based on Sacramento, CA area cost data," or the LLM's own equivalent) at
the top level of every `/estimate/project` response — today both are
computed and then dropped; nothing persists them. This plan adds two
columns to the existing `Project` table:

```python
# On Project (existing model, two new columns):
pricing_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "llm" | "deterministic" | null
pricing_note: Mapped[str] = mapped_column(Text, default="", server_default="")
```

Set from the raw payload (not through `map_payload`, which stays a pure
sheets/items mapper per its own documented contract) in the two places
that already write to `Project` from a payload: `ingest_service.py`'s
`ingest_takeoff()` and `reprocess.py`'s `reprocess_takeoff()`, both of
which already receive the full `payload: dict` and already set
`project.stage`. One line each:
`project.pricing_source = payload.get("source")`,
`project.pricing_note = str(payload.get("location_note") or "")`.

A project ingested before this column existed reads `pricing_source` as
`NULL` — treated identically to `"deterministic"` everywhere below: no
baseline tier, not a false "not sure so let's guess" state.

## Data model

### Company-level (new, one row/table per org except the sparse ones)

```python
class CompanyLaborRate(Base):
    """Singleton per org -- the three role rates and the productivity
    factor CompanySettings.jsx already renders, moved off localStorage."""
    __tablename__ = "company_labor_rates"
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    journeyman_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    foreman_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    apprentice_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    # A multiplier, not a percent, matching settingsStore.js's existing
    # productivityFactor field exactly (1.0 = neutral, 0.97 = 3% more
    # efficient) so the migrated value means the same thing it always did.
    productivity_factor: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=1, server_default="1")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyLaborHoursOverride(Base):
    """Sparse: only items the company has explicitly set custom hours
    for get a row. Everything else falls through to the item's own
    engine-computed labor_hours."""
    __tablename__ = "company_labor_hours_overrides"
    __table_args__ = (UniqueConstraint("org_id", "item_name", name="uq_company_labor_hours_item"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    item_name: Mapped[str] = mapped_column(String(300))
    hours_per_unit: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyMaterialPrice(Base):
    """Sparse, same shape as the hours override -- one row per item name
    the company has priced, matching CompanySettings.jsx's 'Material
    pricing' tab (currently just a free-text 'Pricing source' field this
    replaces with a real list)."""
    __tablename__ = "company_material_prices"
    __table_args__ = (UniqueConstraint("org_id", "item_name", name="uq_company_material_price_item"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    item_name: Mapped[str] = mapped_column(String(300))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### Project-level (new, one row per item at most — same pattern as `ItemEvidenceImage`)

```python
class ProjectLaborLine(Base):
    """Per-item labor overrides. Every field is nullable and independent:
    an estimator can override just the crew mix and leave hours alone,
    or just type a flat rate and leave everything else at its default."""
    __tablename__ = "project_labor_lines"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    hours_override: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    crew_journeyman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crew_foreman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crew_apprentice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_override: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    adjustment_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    adjustment_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectMaterialPrice(Base):
    """Per-item material price override. `source` distinguishes a typed
    project price from a deliberate allowance -- both are the same
    mechanical override, the label is what the estimator meant by it."""
    __tablename__ = "project_material_prices"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    price_override: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20))  # "project_price" | "allowance"
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Both project-level tables are excluded from `snapshots.ITEM_SNAPSHOT_TYPES`
and from the undo/redo action log's per-item snapshot machinery, the same
reasoning as `ItemEvidenceImage`: they are edited through their own
mutation endpoints (below), each independently undoable through the
normal action log, not through the delete/undo item-snapshot path.

## Precedence resolution

Computed fresh on every read — nothing here is pre-computed and stored,
matching `ROADMAP.md` invariant 1 (totals computed in one place).

### Material unit price, per item

1. `ProjectMaterialPrice.price_override` where `source = "project_price"` → **"Project price"**
2. `ProjectMaterialPrice.price_override` where `source = "allowance"` → **"Allowance"**
3. `CompanyMaterialPrice` row matching `item.name` → **"Company price"**
4. **Only if `project.pricing_source == "llm"`:** `item.material_cost /
   item.quantity` → **"Regional baseline"**, with `project.pricing_note`
   available as the row's one-sentence basis.
5. Nothing resolved (tier 4 unreached, or reached but
   `item.material_cost`/`item.quantity` is zero/null) → **Missing
   information**. Its warning names what's needed: a company price, an
   estimator override, or reprocessing the project with the pricing
   assistant available — plain language, never mentioning a model.

### Labor hours per unit, per item

1. `ProjectLaborLine.hours_override` → **"Estimator entered"**
2. `CompanyLaborHoursOverride` row matching `item.name` → **"Company standard"**
3. **Only if `project.pricing_source == "llm"`:** `item.labor_hours /
   item.quantity` → **"Estimated basis"** (not "Catalog default" —
   when the LLM priced the project this figure is per-item and
   location-aware, not a static catalog lookup, and the name should say
   so without naming the mechanism).
4. Nothing resolved → **Missing information**, same as materials tier 5.
   (Previously this had no missing-information case, on the assumption
   `Item.labor_hours` was always populated; that's still true, but its
   value is no longer trusted when it came from the deterministic path.)

### Labor rate ($/hr), per item — independent of hours

1. `ProjectLaborLine.rate_override` → **"Estimator entered"**
2. If the row's crew mix has at least one role count set:
   `(crew_journeyman × company.journeyman_rate + crew_foreman ×
   company.foreman_rate + crew_apprentice × company.apprentice_rate) /
   (crew_journeyman + crew_foreman + crew_apprentice)` → **"Company crew rate"**
3. **Only if `project.pricing_source == "llm"`:** `item.labor_cost /
   item.labor_hours` → **"Estimated basis"**
4. Nothing resolved → the row's hours may still show a status, but a
   labor row with hours but no resolvable rate cannot compute a cost —
   also **Missing information**, its warning naming the same fixes as
   above (set a crew mix, a flat rate, or reprocess with pricing
   support).

### Final labor hours and cost

```
adjusted_hours = resolved_hours_per_unit
                 × item.quantity
                 × (1 + (adjustment_percent or 0) / 100)
                 × company.productivity_factor
labor_cost = adjusted_hours × resolved_rate
```

`productivity_factor` applies to every row uniformly — it's the company
setting, not a per-row choice — exactly matching the mockup's "Company
productivity factor · Whole project" line.

### Status (the real four labels, never a fifth)

Independent of the takeoff item's own review status — a row appears in
these tables regardless of whether the item itself is *Ready to
review*, *Needs attention*, *Missing information*, or *Estimator
approved*, matching the mockup showing 51 rows against "32 of 51
approved":

- **Missing information** — nothing resolves for this row (see the last
  tier of each resolution chain above). On a project priced
  deterministically, this is the *expected* state for every row with no
  override yet, not an edge case — which is the point: a rough guess
  never quietly stands in for a real number. Blocks nothing else in the
  product; it's informational until Estimate Summary exists.
- **Needs attention** — the resolved price came from `CompanyMaterialPrice`
  and its `effective_date` is more than 180 days old ("Stale price," a
  fixed constant for this plan, not a company setting).
- **Estimator approved** — a `ProjectMaterialPrice` row exists (its
  `price_override` is always set when the row exists at all), or a
  `ProjectLaborLine` row exists with at least one of `hours_override`,
  a crew-mix count, `rate_override`, or `adjustment_percent` set — i.e.
  the estimator directly entered or confirmed something on this row.
  Creating a `ProjectLaborLine` with every field still null does not
  happen through the UI, so existence alone is equivalent to this.
- **Ready to review** — resolved from a company or regional tier, no
  override yet.

The precedence-tier label ("Company price," "Regional baseline," etc.)
renders as its own tag, styled distinctly from the four-label status
pill — the same separation `noteVocabulary.js`'s `--slate`/`--plum`
tokens already enforce between a note's status and an item's status.
"Stale price" is the *Needs attention* status with its icon and amber
color; the tier tag next to it still reads "Company price," so an
estimator sees both what the number is sourced from and that it's aged
out, never a fifth invented color.

## API surface

New router, `api/app/takeoff/pricing_router.py`, mounted in `main.py`
alongside the existing routers — split out for the same reason
`mutations.py` was split from `router.py`: this adds a real block of new
endpoints, and keeping them in `mutations.py` would push it well past
this project's file-size convention.

```
GET   /api/projects/{project_id}/labor            -> list[LaborRowOut]
PATCH /api/items/{item_id}/labor                   -> LaborRowOut
GET   /api/projects/{project_id}/material-pricing  -> list[MaterialRowOut]
PATCH /api/items/{item_id}/material-price           -> MaterialRowOut
```

Both `GET` responses carry the project's `pricingSource` and
`pricingNote` once at the top level (not repeated per row) — the
frontend uses `pricingSource` to render the "reprocess to unlock a
baseline" prompt when it's not `"llm"`, and shows `pricingNote` as the
one-sentence basis wherever a row's tier is "Regional baseline" or
"Estimated basis."

```

GET   /api/company/labor-rates                     -> CompanyLaborRatesOut
PUT   /api/company/labor-rates                      -> CompanyLaborRatesOut
GET   /api/company/material-prices                  -> list[CompanyMaterialPriceOut]
PUT   /api/company/material-prices/{item_name}       -> CompanyMaterialPriceOut
DELETE /api/company/material-prices/{item_name}      -> 204
GET   /api/company/labor-hours-overrides             -> list[CompanyLaborHoursOverrideOut]
PUT   /api/company/labor-hours-overrides/{item_name} -> CompanyLaborHoursOverrideOut
DELETE /api/company/labor-hours-overrides/{item_name} -> 204
```

Every `PATCH`/`PUT`/`DELETE` above routes through `actions.commit()`,
same convention as every other mutation in this codebase (attribution,
audit trail, undo). Company-level edits are logged and attributed but
are **not** added to `undo.REVERSIBLE` — they affect every project in the
org, and this codebase's existing undo stack is explicitly project- and
item-scoped; extending it to cross-project company settings is a
different, unstarted design question this plan doesn't open. Project-level
edits (`ProjectLaborLine`, `ProjectMaterialPrice`) *are* added to
`REVERSIBLE`, consistent with `edit`/`approve`/`scale`.

Tenancy: every route follows the existing `load_item`/`load_project`
pattern; company routes resolve the org from `current_user` the same way
every other company-scoped read already does.

## Frontend

New files, following this codebase's one-file-one-responsibility
convention:

```
src/components/labor/
  LaborWorkspace.jsx        the screen: table, crew-mix editor, adjustment input
  laborColumns.js           column defs, mirroring spreadsheetColumns.js's shape
src/components/pricing/
  MaterialPricingWorkspace.jsx   the screen: table, override editor
  pricingColumns.js
```

Both screens are plain tables in this codebase's existing style (see
`TakeoffSpreadsheet.jsx` for the pattern: sortable columns, tabular
numerals on every quantity/cost, inline edit on a cell, autosave with the
top bar's `Saving…`/`Saved` indicator — no save button). Filter chips for
the four statuses, matching every other workspace's filter convention.

`src/lib/store/api.js` / `api-mapping.js` gain the store methods for the
eight endpoints above, following the exact existing pattern (`mapItem`
etc.) — plain fetch wrappers, no new abstraction.

`src/components/settings/CompanySettings.jsx`: the `labor`, `adjustments`,
and `material` tabs' `FIELDS` entries stop reading/writing
`settingsStore.js` and instead call the new company endpoints. The
`material` tab's single `materialSource` text field is replaced with a
real add/edit/remove list backed by `CompanyMaterialPrice` (a small table
inline in that tab, not a separate screen). `profile`, `markup`, and
`export` tabs are untouched, still on `localStorage` — see Scope above.

`ProjectNav.jsx`: flip `labor` and `pricing` (Material pricing) from
`built: false` to `built: true`. `assemblies` and `estimate` (Estimate
summary) stay `built: false` — untouched by this plan.

## Testing

**Backend:**
- Precedence resolution, both tables: a unit test per tier, confirming
  the source label matches and that a lower tier is correctly skipped
  when a higher one is present (mirrors the discipline
  `test_ingest_mapping.py` already applies to `normalize_point`).
- `pricing_source` gating, the load-bearing new behavior: a project with
  `pricing_source = "deterministic"` never surfaces "Regional baseline"
  or "Estimated basis" for any row, even when `Item.material_cost`/
  `labor_hours` are nonzero — it resolves to Missing information instead.
  A project with `pricing_source = "llm"` does surface that tier. A
  project with `pricing_source = NULL` (pre-dates the column) behaves
  identically to `"deterministic"`.
- `ingest_service.py` and `reprocess.py` both set `project.pricing_source`
  and `project.pricing_note` from the payload's top-level `source`/
  `location_note` fields.
- Missing-information case: an item with `material_cost = 0` and no
  override/company price resolves to that status, not a crash on
  division by a zero quantity.
- Stale-price threshold: a company price row with `effective_date` 181
  days old resolves *Needs attention*; 179 days old resolves *Ready to
  review* (boundary test).
- Crew-mix blended rate: a mix of all three roles computes the correct
  weighted average; a rate override skips crew-mix computation entirely.
- Tenancy: every new endpoint gets a row in `test_tenancy.py`'s
  `TENANCY_TABLE`, same convention every other route already follows.
- `productivity_factor` applies once per row, not compounded with
  anything else.

**Frontend:**
- Both workspaces render rows for every countable item regardless of its
  takeoff status (the "32 of 51" case).
- Editing a project override round-trips through the store and updates
  the row's status to *Estimator approved*.
- The precedence-tier tag and the four-label status pill render as two
  visually distinct elements, never merged into one badge.
- `ProjectNav.jsx`'s existing nav test is updated for the two workspaces
  flipping to `built: true`.

## Known limitations after this ships

- Company price/hours matching is by exact item name. An LLM-classified
  item whose wording drifts from a company entry's name falls through to
  a coarser tier rather than matching — accepted per the "fails safe, not
  silently wrong" reasoning above. Precise matching is quote-matching's
  job, not this plan's.
- No supplier quote or price-sheet upload of any kind. Every price in
  this plan is either the LLM-priced project's ingest-time figure or
  something a person typed in directly.
- **A project processed without a configured pricing assistant shows
  Missing information for nearly every row** until the estimator or
  company fills in overrides, or the project is reprocessed with one
  available. This is deliberate (see "no hardcode" above), but it means
  the two projects already in this database from earlier testing will
  show almost entirely Missing information on first load, since their
  `pricing_source` is `NULL`.
- No assemblies, so no derived wire/conduit/box material rows — only
  rows that map 1:1 to an approved takeoff item.
- The 180-day staleness threshold is a fixed constant, not configurable
  per company.
- `CompanySettings.jsx`'s other tabs (profile, markup, export) and all of
  `ProjectSettings.jsx` remain on `localStorage`, unmigrated.
