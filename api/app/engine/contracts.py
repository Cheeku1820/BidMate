"""The typed records the five agents hand off to each other.

Agents share a store, not a transcript (CLAUDE.md): each stage emits a
typed record the next stage consumes, never prose. That is what keeps
extracted document text from steering a downstream decision (invariant
11) and what makes each agent separately measurable. These dataclasses
are that contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DetectedSheet:
    """Documents agent output: one electrical sheet in the set."""

    page_index: int  # 0-based page in the source PDF
    number: str  # e.g. "E2.1" (from the title block; "" if unread)
    title: str
    discipline: str
    scale: str  # "" when none was found in the title block
    width_pt: float
    height_pt: float
    # Drawing region in page points (x0, y0, x1, y1): the area device tags
    # are counted within, excluding the title-block strip and border.
    region: tuple[float, float, float, float]
    schedule_text: str = ""  # raw schedule/legend text for Classification
    legend: list["LegendEntry"] = field(default_factory=list)  # parsed rows from schedule_text
    unreadable_reason: str = ""  # set when the sheet could not be read


@dataclass
class Placement:
    x: int
    y: int


@dataclass
class DeviceCluster:
    """Counting agent output: an *unlabelled* group of identical tags with
    exact coordinates. Counting does not know what these are."""

    tag: str
    sheet_page_index: int
    placements: list[Placement] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.placements)


@dataclass
class ClassifiedItem:
    """Classification agent output: a cluster given a catalog identity and a
    review status. Still not approved -- a person does that."""

    catalog_id: str
    name: str
    system: str
    category: str
    unit: str
    symbol: str
    quantity: int
    sheet_page_index: int
    placements: list[Placement]
    status: str  # ready | attention | missing (never approved here)
    warning: dict | None = None  # four-field shape when status != ready
    source_tag: str = ""


@dataclass
class PricedItem:
    """Pricing agent output: a classified item with cost attached. The engine
    stops at total direct cost -- no markup, overhead, or profit."""

    item: ClassifiedItem
    material_cost: float  # quantity * unit material
    labor_hours: float  # quantity * unit labor hours
    labor_cost: float  # labor_hours * blended rate
    total_direct_cost: float  # material_cost + labor_cost
    assembly: "Assembly | None" = None  # the supporting material behind this item


@dataclass
class TakeoffResult:
    """The whole pipeline's output for one document."""

    sheets: list[DetectedSheet]
    items: list[PricedItem]
    labor_rate: float

    @property
    def material_total(self) -> float:
        return round(sum(p.material_cost for p in self.items), 2)

    @property
    def labor_hours_total(self) -> float:
        return round(sum(p.labor_hours for p in self.items), 2)

    @property
    def labor_cost_total(self) -> float:
        return round(sum(p.labor_cost for p in self.items), 2)

    @property
    def total_direct_cost(self) -> float:
        return round(sum(p.total_direct_cost for p in self.items), 2)


@dataclass
class LegendEntry:
    """Documents agent output: one row of a legend or abbreviations block,
    read as structured data rather than left as a wall of text. `kind`
    separates a drawn symbol ("S" = single pole switch) from a written
    abbreviation ("WP" = weatherproof), because the two mean different
    things to Classification: a symbol names a device, an abbreviation
    usually modifies one."""

    symbol: str
    description: str
    kind: str  # "symbol" | "abbreviation"


@dataclass
class AssemblyLine:
    """One material line inside an assembly -- the box, the connector, the
    wire. Division 26 only."""

    catalog_id: str
    name: str
    quantity: float
    unit: str
    material_cost: float  # dollars per unit
    labor_hours: float  # crew hours per unit


@dataclass
class Assembly:
    """Pricing agent output: what a device actually costs to install once
    its supporting material is counted. A receptacle is not a receptacle --
    it is a receptacle, a box, a plate, wire, and connectors (spec 2.4)."""

    parent_catalog_id: str
    lines: list[AssemblyLine] = field(default_factory=list)

    @property
    def material_cost(self) -> float:
        return round(sum(l.material_cost * l.quantity for l in self.lines), 2)

    @property
    def labor_hours(self) -> float:
        return round(sum(l.labor_hours * l.quantity for l in self.lines), 3)


@dataclass
class Proposal:
    """Conversation agent output. It proposes; a person applies it through
    the same path a manual edit takes (spec 2.5, ROADMAP invariant 9).
    Deliberately carries no method that writes anything."""

    intent: str  # "reclassify" | "exclude" | "set_context" | "unknown"
    target_item_ids: list[str]
    field: str
    value: str
    summary: str
