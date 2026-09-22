# Connectors — research notes

**Date:** 2026-09-21
**Stream:** C (`workstreams-2026-09.md` §1.C, §2)
**Status:** Scratch. What was read, what it said, what it rules out. The decisions live in `docs/specs/connectors-overview.md`, `connector-buildingconnected.md`, and `connector-excel-export.md`.

## 1. BuildingConnected (Autodesk Platform Services)

Read on 2026-09-21 from the APS documentation site (pages are client-rendered; read through the browser pane).

### 1.1 What the API is

One REST API, `https://developer.api.autodesk.com/construction/buildingconnected/v2/…` (a `v3` landed March 2026 — same objects, `projectSize` no longer converted to square feet, a `bidFormId` on projects, fewer project state transitions; nothing that touches what we use). Two products sit on it:

- **BuildingConnected Pro** — the *GC side*: projects, bid packages, invites, bids, bid forms. Needs a BC Pro subscription.
- **Bid Board Pro** — the *subcontractor side*: **opportunities**. Every invite a GC sends becomes one opportunity on the invited company's Bid Board. Needs a Bid Board Pro subscription.

An electrical sub is a Bid Board user. Everything we can read on their behalf is the Opportunities group, plus `GET users/me` and `GET offices` (no subscription needed).

### 1.2 Authentication

- **3-legged OAuth only.** The estimator signs in with their Autodesk ID and authorises our registered APS app. Scopes: `data:read` for everything we do (`data:create data:read data:write` is what the getting-started page asks for; we only read).
- Access tokens last 60 minutes. **Refresh tokens expire after 14 days** and can be exchanged for a new one at any time before that — so a connection that is refreshed at least fortnightly stays alive indefinitely, and one left idle for two weeks has to be re-authorised by the person.
- Prerequisites on the estimator's side: a BuildingConnected account whose user is **linked to an Autodesk ID** (a one-time step in BuildingConnected's own settings), and a Bid Board Pro seat, either through their office or assigned at manage.autodesk.com. `GET opportunities` returns 403 otherwise.
- Prerequisites on our side: **register an app on aps.autodesk.com** (Traditional Web App type), select the BuildingConnected API under API Access, set the callback URL, keep the client id and secret in `api/.env`. The opportunities reference page says "Contact your sales representative to get access to the BuildingConnected API" — expect an approval step with Autodesk before production use. A `test` environment (`x-bc-mode: test` header, read-only, canned data) exists for developers without a subscription.
- **Nobody on the team should sign up for anything as part of this stream.** The user has to: create the APS app, and, for a real test, have one design-partner estimator with Bid Board Pro connect their account.

### 1.3 The opportunity object

`GET /opportunities` — cursor paginated (`cursorState`, `limit` default 100), filter `filter[updatedAt]=<iso>..` (open ranges allowed) and `filter[clientCompanyId]`. `GET /opportunities/{id}` for one. Fields that matter to us, with the ones we map:

| Field | Meaning | Maps to |
|---|---|---|
| `id` (24-char) | The opportunity | `external_id` on our link row |
| `name`, `number` | Project name, GC's project number | `project.name`, `project.number` |
| `client.company.name` | The GC (or whoever sent the invite) | `project.customer` |
| `client.lead` (name, email, phone) | The GC's contact | shown on the project overview |
| `location.complete`, `location.zip`, `.city`, `.state` | Job site | `project.location`, `project.postal_code` |
| `dueAt` | Bids due | `project.bid_due_date` |
| `rfisDueAt`, `jobWalkAt`, `expectedStartAt`, `expectedFinishAt` | Other dates | shown; `rfisDueAt` is the one an estimator acts on |
| `tradeName` | "Electrical" | filter: only electrical opportunities are offered |
| `projectInformation`, `tradeSpecificInstructions` (HTML) | The GC's instructions | shown as text; treated as data, never instruction |
| `architect`, `engineer`, `propertyOwner`, `marketSector`, `projectSize` | Context | shown |
| `isNdaRequired` | NDA before files | the confidentiality flag on our link row |
| `submissionState`, `outcome.state`, `workflowBucket` | Where the bid is | the "declined / submitted / won" state we show, read-only |
| `clientValues.*` | The GC's original values where the sub overrode them on Bid Board | we take `clientValues.dueAt` when it differs — the GC's date is the real deadline |
| `source` | `BUILDINGCONNECTED` (a real invite) vs `EMAIL`, `MANUAL`, `IMPORTED` … (a foreign opportunity the sub keyed in or forwarded) | both are offered; a foreign one carries whatever the sub typed |
| `isParent`, `parentId`, `groupChildren` | Bid Board grouping (several GCs bidding the same job) | children are offered individually; a group parent is not — one project per invite, the estimator can link two later |
| `updatedAt` | Last change | the poll cursor |

### 1.4 The documents — the finding that shapes the design

**The API does not expose an opportunity's files to the bidder.** The field guide's limitations list is explicit: "No ability to manage opportunity files" and "No file management except through Docs." The only file paths in the API are:

- `GET bids/{bidId}/attachments/{attachmentId}` → a signed S3 URL — that is the bidder's *own proposal* attached to a submitted bid, not the GC's drawings.
- Forma Data Management folders (`currentAccDocsFolderId` on a *project* or *bid package*) — GC-side objects on a BC Pro subscription, readable only by the GC's own token. The sub is not a member of the GC's Autodesk hub; BuildingConnected's sharing "overrides any permissions set on the folder in Forma Data Management", i.e. the sharing happens inside BuildingConnected's web app, not through the Data Management API.

What the sub *can* do, in the web app: open the opportunity → Files tab → **Download All** (a ZIP, up to 4.5 GB), or download folders individually (each a ZIP), or single PDFs. Files are organised in whatever folders the GC made — commonly `Drawings/`, `Specifications/`, `Addenda/` or `Addendum 1/`.

Consequence: "a bid invitation becomes a project with its documents already attached" is achievable for the *project* half (name, GC, address, ZIP, due date, instructions — everything screen B asks for) and **not** for the documents half through this API. The documents arrive as a ZIP the estimator downloads from BuildingConnected and drops on screen C. That drop is the piece worth building well: a ZIP is expanded in the browser, folder names decide the document type, and every file goes through the existing upload route one at a time — the API never opens an archive.

Not a workaround we should take: scraping the web app's download with the estimator's session, or asking them for their BuildingConnected password. Both are prohibited by our own rules and by Autodesk's terms.

### 1.5 Change notification

Two mechanisms:

- **Webhooks** (system `autodesk.construction.bc`): `opportunity.created`, `opportunity.status.updated`, `opportunity.comment.created/updated/deleted`, `bid.created`. 3-legged token only; the hook is created per connected user; callback URL must be public HTTPS. There is **no `opportunity.updated`** for a changed due date or new files — and files are invisible to the API anyway, so "an addendum landed" is not an event we can receive. `opportunity.comment.created` is the closest thing: GCs often post "Addendum 2 posted" as a comment.
- **Polling** `GET /opportunities?filter[updatedAt]=<last seen>..` — cheap (1,000 requests/minute per user account), and catches due-date changes, status changes, and new invites alike.

Decision: **poll, don't hook**, for the first slice. A webhook needs a public callback (the API has no inbound URL from the internet today), a hook per user with 3-legged auth, and still cannot tell us about files. A poll every 15 minutes from the worker, per connected user, covers new invites and moved deadlines. Comments are fetched with the opportunity (`GET opportunities/{id}/comments`) and shown; a new comment on a linked project is surfaced as a notice.

### 1.6 Rate limits

1,000 requests/minute per user account across all BC endpoints; 60/minute per client id for writes (we make none). A 15-minute poll of one list call per connected user is nowhere near either.

### 1.7 Sources

- Field guide: https://aps.autodesk.com/en/docs/buildingconnected/v2/developers_guide/field_guide/buildingconnected/
- Getting started (subscriptions per endpoint group, app registration, test environment): https://aps.autodesk.com/en/docs/buildingconnected/v2/tutorials/buildingconnected/getting-started
- `GET opportunities` reference (full object, filters, pagination): https://aps.autodesk.com/en/docs/buildingconnected/v2/reference/http/buildingconnected-opportunities-GET
- Files tutorial (Forma Data Management, bid attachments): https://aps.autodesk.com/en/docs/buildingconnected/v2/tutorials/buildingconnected/manage-files-using-docs
- v2→v3 migration guide (March 2026): https://aps.autodesk.com/en/docs/buildingconnected/v2/developers_guide/migration-guides/buildingconnected-v2-to-v3
- Webhook events: https://aps.autodesk.com/en/docs/webhooks/v1/reference/events/buildingconnected_events
- Rate limits: https://aps.autodesk.com/en/docs/buildingconnected/v2/developers_guide/rate-limits/productspecific-rate-limits
- How subcontractors download bid files (the ZIP): https://support.buildingconnected.com/hc/en-us/articles/360016482074
- OAuth scopes: https://aps.autodesk.com/en/docs/oauth/v2/developers_guide/scopes/

## 2. The firm's Excel template

Measured 2026-09-21 with openpyxl on the two estimate workbooks in `bid_examples/` (gitignored; nothing below is a price).

### 2.1 Layout, common to every sheet

- Header block, rows 1–4 (FedEx) or 1–5 (Gerber), in column A/C: `PROJECT` / name, `Location` / address (FedEx puts the address in the `Date of plans` row — the template's header rows are misaligned on that bid), `Date of plans` / Excel serial date, `Comments`, `ALL Trades` / `=E13` (a formula pointing at the first section heading). `PR ID 7876` in column O and `Rev 0 NA` in column Q on row 1.
- **Column header row** — row 5 (FedEx) or row 6 (Gerber). The 17 names, A→Q:
  `SR #`, `DWG. NO.`, `DETAIL NO.`, `CSI NO.`, `DESCRIPTION`, `QTY.`, `WASTE`, `QTY. W/ WASTE`, `UNIT`, `UNIT LABOR HOURS`, `TOTAL LABOR HOURS`, `LABOR RATE`, `TOTAL LABOR COST`, `UNIT MATERIAL COST`, `TOTAL MATERIAL COST`, `TOTAL`, `TOTAL COST`.
- Column widths (both bids identical): A 5.3, B 11.2, C 12.5, D 13.8, E 49.3, F 6.8, G 6.3, H 8.3, I 5.5, J 12.1, K 13.5, L 12.1, M 13.7, N 13.7, O 18.5, P 17.5, Q 12.8.
- No freeze panes; occasional merged cells in B/C where one drawing reference spans several lines (Gerber `B16:B24`).

### 2.2 Row kinds and their formulas

| Kind | How it reads | Cells |
|---|---|---|
| Section heading | `CSI NO.` = `01 00 00` / `26 00 00`, `DESCRIPTION` in caps | On the `26 00 00` row only: N = `PER HOUR LABOR RATE`, P = the rate (85). Every line's `LABOR RATE` is `=$P$13` (absolute reference to that cell) |
| Group heading | `DESCRIPTION` only — `Demolition`, `Light Fixtures`, `Lighting Controls`, `Power Fixtures`, `Low Voltage Fixtures`, `Electrical Panel`… | nothing else |
| Line | `QTY.` filled | A `=IF(H<r><>"",1+MAX($A$6:A<r-1>),"")` (running serial); B/C drawing and detail numbers (`E-2.0`, `E-4.0`; multi-line when several); E description, multi-line `Name\nManufacturer: …\nModel: …\nWattage: …` on fixtures; F qty; G waste (0); H `=F*(1+G)`; I unit `EA` / `LF` / `LS`; J unit hours; K `=J*H`; L `=$P$13`; M `=L*K`; N unit material; O `=N*H`; P `=O+M`; Q empty |
| Blank spacer | empty row between groups | A carries the serial formula still |
| Sub Total | `DESCRIPTION` = `Sub Total`, Q = `=SUM(P<first>:P<last>)` over the section's lines | only Q |
| Markup block | A reads `SUB - TOTAL`, `OVERHEAD AND PROFIT`, `TAX`, `BID BOND`, `CONTIGENCIES` (sic), `TOTAL TRADES COST` | SUB-TOTAL: M `=SUM(M…)`, O `=SUM(O…)`, Q `=SUM(Q…)`. Each rate row: L = rate (0.10 / 0.07 / 0.015 / 0.03 on Gerber; 0.20 / 0.08875 / 0.015 / 0.03 on FedEx), M `=M<sub>*L<r>`, N `=N<sub>*L<r>`, O `=O<sub>*L<r>`, Q `=M<r>+O<r>`. TOTAL TRADES COST: M/N/O/Q `=SUM(<sub>:<contingency>)` |

Every rate is applied to labor and material alike and the four are summed — an additive stack, tax on labor included. Recorded, not judged.

### 2.3 Phases

Gerber has three sheets: `PHASE I`, `PHASE II (2)` (each a complete estimate with its own General Conditions, Demolition, groups, Sub Total and markup block) and `SUMMARY BID` (one `LS` line per phase under `26 00 00`, hours and material typed from each phase's totals, then the same markup block). FedEx has one sheet, `ESTIMATE`. So: **one estimate sheet per phase, plus a summary sheet when there is more than one phase.**

Phases as a record are stream D's spec, not ours. The export has to work today with one phase (every item, one sheet named `ESTIMATE`) and take a phase list from D's model when it lands — a sheet per phase plus `SUMMARY BID`.

### 2.4 What is already in the repo

- Current export is client-side CSV from `src/components/export/ExportPreview.jsx`, ten columns, totals from the store's `computeTotals()`. No API route.
- `openpyxl>=3.1` is already a dependency (`api/app/market/price_sheet.py` builds and reads the supplier price request).
- `api/app/takeoff/totals.py` holds `countable_items()` and `approved_totals()` — the one place, invariant 1.
- Markup and export preferences (`wastePercent`, `overheadPercent`, `profitPercent`, `exportFormat`, `includeSourceRefs`) live in `src/lib/settingsStore.js` — **browser localStorage, not the API.** The workbook is generated server-side, so the rates it writes have to arrive from the client with the export request (typed by the estimator, prefilled from those settings) or those settings have to move to the API first. The spec chooses the former: the estimator types them on the export preview, and the values are recorded in the export action.
- The parser side of the same template — header detection, row kinds, `LineRecord` / `MarkupRecord` — is designed in `firm-price-book.md` on `feat/corpus-price-book` (`docs/superpowers/specs/2026-09-15-firm-price-book-design.md`). The writer here is its inverse and should share the column list and row-kind vocabulary with it when both land.

## 3. The others, briefly (for the overview's ranking)

- **Procore** — versioned REST; a sub gets free project access on the GC's Procore; drawings, specs, RFIs, submittals, change orders are all first-class; an OAuth app + Marketplace listing; a sandbox with seeded data. Inbound documents *are* downloadable (Drawings and Documents endpoints), which is the thing BuildingConnected can't do — but only after award, or when a GC runs bidding out of Procore (fewer do). https://developers.procore.com/
- **McCormick** — imports CSV takeoff lists and Trade Service / NetPricer price files; export is CSV to Foundation. **Accubid** (Trimble) — "Accubid Integrator" exports to Excel/accounting; imports from Trimble's own takeoff tools. **ConEst IntelliBid** — CSV import/export, links to accounting. All three: a CSV in their column order is the integration; none has a public API worth building against.
- **Foundation / Sage 100 Contractor / QuickBooks** — job budget import from CSV/IIF; QuickBooks Online has a real REST API (OAuth, `Estimate` object) if a won bid should become a QuickBooks estimate.
- **Kojo** — procurement; supplier catalogue and pricing integrations (Graybar direct); no public developer program found — partner-only. The material list to Kojo is a CSV requisition today.
- **Bluebeam** — Studio API for markups; not on the path.

## 4. Where this stopped, 2026-09-22

Brainstorm tabled before the specs were written. The open decision, recorded so the next session does not re-derive it:

**The firm's invitations arrive mostly by email and from public bid sites, not through BuildingConnected.** That demotes the connector §2 of `workstreams-2026-09.md` ranked first. A BuildingConnected connection needs a paid Bid Board Pro seat and Autodesk's sign-off on API access, and even then cannot fetch the drawings (§1.4). Speccing it first would serve a path this firm barely uses.

What the ranking looks like once that is true — inbound, by how much each removes from the estimator's day:

1. **Forward-the-invite email.** A per-org `bids@…` address. Every platform (BuildingConnected, PlanHub, SmartBid, iSqFt, Procore, Blue Book) sends a templated invitation email, and so do GCs with no platform at all. The email becomes a draft project — GC, project name, bid due date, site address, a link back to the plan room — with its attachments stored. Needs an inbound-email provider (SES or Postmark inbound → the API), no third-party account, no approval. Email content is untrusted input, parsed as data, and a parsed project is a draft a person confirms. This is BuildingConnected's own Bid Forwarding feature, done on our side.
2. **Set drop on screen C.** The estimator drops the ZIP a plan room's "Download All" produced, or a folder. Expanded in the browser; folder names (`Drawings/`, `Specs/`, `Addendum 2/`) decide the document type; each PDF goes through the existing `store_upload` route one at a time. Client-side only — the API never opens an archive. This is the documents half of every other inbound connector, so it is worth building whichever one leads.
3. **Paste a link.** Dropbox, Box, ShareFile, Google Drive, OneDrive — usually the link *inside* the forwarded email. Dropbox and Box public links need no account; the others need an OAuth app we register. The fetch runs in the worker, which already has egress; never in the API.
4. **Procore.** The only platform where a sub can actually download drawings, specs and addenda over an API, and where RFIs could go out later. Needs a developer app and a Marketplace review; sandbox with seeded data exists. Applies when the GC runs bidding or the job in Procore.
5. **ConstructConnect** (owns iSqFt, BidClerk, SmartBid, PlanSwift). REST, `x-api-key` in a query parameter, sandbox and production hosts published at developer.io.constructconnect.com; the endpoint list itself is behind a sign-in, so whether plan documents are downloadable is unconfirmed. Worth it only if the firm already subscribes.
6. **Dodge Construction Network.** REST, leads plus "plans and specs to extract product mentions… at scale", under an enterprise API licence addendum priced for CRM and analytics buyers. Not for a firm this size.
7. **PlanHub.** API is project leads and contacts — IDs, stages, addresses, values, bidding dates. No documents, no invitation object. Quote-based licence. Leads only.
8. **BuildingConnected.** §1 above. Project prefill and deadline polling for firms that have Bid Board Pro; no documents; keep it as one section of an inbound spec rather than its own first connector.
9. **Public procurement portals** — BidNet Direct, DemandStar, Bonfire, OpenGov, PlanetBids. No vendor-facing API at any of them (SAM.gov is the federal exception); third parties resell scraped datasets. Not a connector. Items 1 and 2 cover them.

**The question that was open when this stopped:** whether the estimator would genuinely forward invitation emails to an address, or whether the natural motion is "I have already downloaded the set, get it in." Both get built; that answer decides which is the front door, and therefore which spec is written first.

Sources for this section: [ConstructConnect developer overview](https://developer.io.constructconnect.com/overview), [Dodge construction data API](https://www.construction.com/apis/), [Dodge API licence addendum](https://www.construction.com/wp-content/uploads/2025/09/DCN_API-License_Addendum_20250812-FINAL.pdf), [PlanHub API](https://planhub.com/api/), [Procore developers](https://developers.procore.com/), [OpenGov supplier portal](https://opengov.com/products/procurement/suppliers/), [DemandStar](https://network.demandstar.com/).
