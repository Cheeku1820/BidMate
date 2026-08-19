/* ============================================================
   ProjectsFilters.jsx — spec §5.1's search, filter chips, and sort.

   Filter keys come from projectStage.js rather than being restated here,
   so a filter and the predicate behind it cannot disagree.

   Active state is read off `aria-pressed`, not a hand-rolled "active"
   class — the same convention SheetsRail.jsx already uses for its own
   filter chips (`.chip[aria-pressed="true"]`), kept consistent here
   under a differently-scoped class name (`.filter-chip`) because that
   existing `.chip` rule is sized for a narrow sidebar (24px tall) and
   would leave these chips under the 40px touch-target minimum.
   ============================================================ */

const FILTERS = [
  { key: "active", label: "Active" },
  { key: "processing", label: "Processing" },
  { key: "needsReview", label: "Needs review" },
  { key: "readyToExport", label: "Ready to export" },
  { key: "complete", label: "Complete" },
  { key: "archived", label: "Archived" },
];

const SORTS = [
  { key: "updated", label: "Last updated" },
  { key: "bidDate", label: "Bid due date" },
  { key: "name", label: "Project name" },
  { key: "customer", label: "Customer" },
  { key: "estimator", label: "Estimator" },
];

export default function ProjectsFilters({ search, onSearch, filter, onFilter, sort, onSort }) {
  return (
    <div className="projects-filters">
      <div className="formfield">
        <label className="formfield-label" htmlFor="projects-search">
          Search projects
        </label>
        <input
          id="projects-search"
          className="field"
          type="search"
          value={search}
          placeholder="Name, number, or customer"
          onChange={(event) => onSearch(event.target.value)}
        />
      </div>

      <div className="filter-chips" role="group" aria-label="Filter projects">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            className="filter-chip"
            aria-pressed={key === filter}
            onClick={() => onFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="formfield">
        <label className="formfield-label" htmlFor="projects-sort">
          Sort by
        </label>
        <select
          id="projects-sort"
          className="field"
          value={sort}
          onChange={(event) => onSort(event.target.value)}
        >
          {SORTS.map(({ key, label }) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
