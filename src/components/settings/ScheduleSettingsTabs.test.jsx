import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CrewsAndStagesTab, LeadTimesTab } from "./ScheduleSettingsTabs.jsx";

function crewStore(overrides = {}) {
  return {
    getStageSplits: vi.fn().mockResolvedValue([
      {
        categoryKey: "devices", categoryLabel: "Devices", demolition: 0, roughIn: 45,
        wirePull: 25, gear: 0, trim: 25, closeout: 5, firmEdited: false,
      },
    ]),
    getStageCrews: vi.fn().mockResolvedValue([
      {
        stage: "rough_in", label: "Rough-in", foreman: 1, journeyman: 2, apprentice: 2,
        productiveHoursPerDay: 6, productivityFactor: 1, maxCrew: 6, firmEdited: false,
      },
    ]),
    getScheduleSettings: vi.fn().mockResolvedValue({ leadTimeStaleDays: 60 }),
    setStageSplit: vi.fn(),
    setStageCrew: vi.fn(),
    setScheduleSettings: vi.fn().mockResolvedValue({ leadTimeStaleDays: 30 }),
    ...overrides,
  };
}

describe("Crews and stages", () => {
  it("labels an untouched row as the default, never a recommendation", async () => {
    render(<CrewsAndStagesTab store={crewStore()} />);
    await waitFor(() => expect(screen.getAllByText("Default").length).toBe(2));
    expect(screen.queryByText(/recommend/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/industry/i)).not.toBeInTheDocument();
  });

  it("refuses a split that does not total 100 and says so in words", async () => {
    const store = crewStore();
    render(<CrewsAndStagesTab store={store} />);
    await screen.findByLabelText("Devices Trim");
    fireEvent.change(screen.getByLabelText("Devices Trim"), { target: { value: "20" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await screen.findByText("The six stages have to add up to 100 percent.");
    expect(store.setStageSplit).not.toHaveBeenCalled();
  });

  it("saves a split that totals 100", async () => {
    const store = crewStore({
      setStageSplit: vi.fn().mockResolvedValue({
        categoryKey: "devices", categoryLabel: "Devices", demolition: 0, roughIn: 50,
        wirePull: 20, gear: 0, trim: 25, closeout: 5, firmEdited: true,
      }),
    });
    render(<CrewsAndStagesTab store={store} />);
    await screen.findByLabelText("Devices Rough-in");
    fireEvent.change(screen.getByLabelText("Devices Rough-in"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("Devices Wire pull"), { target: { value: "20" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(store.setStageSplit).toHaveBeenCalledWith("devices", expect.objectContaining({ roughIn: "50" })));
  });

  it("saves the staleness window", async () => {
    const store = crewStore();
    render(<CrewsAndStagesTab store={store} />);
    const field = await screen.findByLabelText("Lead times count as out of date after");
    fireEvent.change(field, { target: { value: "30" } });
    fireEvent.blur(field);
    await waitFor(() => expect(store.setScheduleSettings).toHaveBeenCalledWith({ leadTimeStaleDays: 30 }));
  });
});

describe("Lead times", () => {
  it("shows every class as not entered until someone quotes one", async () => {
    render(<LeadTimesTab store={{ getCompanyLeadTimes: vi.fn().mockResolvedValue([]) }} />);
    await waitFor(() => expect(screen.getAllByText("— Not entered")).toHaveLength(8));
  });

  it("needs weeks and who quoted it before it will save", async () => {
    const store = {
      getCompanyLeadTimes: vi.fn().mockResolvedValue([]),
      setCompanyLeadTime: vi.fn().mockResolvedValue({
        itemClass: "switchboard", leadWeeks: 52, sourceLabel: "Eaton rep", quotedAt: "2026-09-01",
      }),
    };
    render(<LeadTimesTab store={store} />);
    const weeks = await screen.findByLabelText("Switchboards weeks");
    const save = screen.getAllByRole("button", { name: "Save" })[0];
    expect(save).toBeDisabled();

    fireEvent.change(weeks, { target: { value: "52" } });
    expect(screen.getAllByRole("button", { name: "Save" })[0]).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Switchboards who quoted it"), { target: { value: "Eaton rep" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() =>
      expect(store.setCompanyLeadTime).toHaveBeenCalledWith(
        "switchboard",
        expect.objectContaining({ leadWeeks: 52, sourceLabel: "Eaton rep" }),
      ),
    );
  });
});
