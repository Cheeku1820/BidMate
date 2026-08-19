import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import NewProject from "./NewProject.jsx";

describe("NewProject", () => {
  it("labels every field visibly and persistently", () => {
    render(
      <MemoryRouter>
        <NewProject store={{ createProject: vi.fn() }} />
      </MemoryRouter>,
    );
    for (const label of [
      /project name/i, /internal number/i, /customer/i,
      /project address/i, /bid due date/i, /construction type/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it("does not expose labor or pricing settings", () => {
    // Spec §6.1: advanced labor and pricing settings do not appear
    // during creation.
    render(
      <MemoryRouter>
        <NewProject store={{ createProject: vi.fn() }} />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/labor rate/i)).toBeNull();
    expect(screen.queryByLabelText(/markup/i)).toBeNull();
  });

  it("blocks submission with a message beside the field when the name is blank", async () => {
    const createProject = vi.fn();
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(createProject).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a project name/i)).toBeTruthy();
  });

  it("creates the project with the entered values", async () => {
    const createProject = vi.fn().mockResolvedValue({ id: "p9", name: "Oakview High School" });
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project name/i), "Oakview High School");
    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.type(screen.getByLabelText(/customer/i), "Swinerton");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(createProject).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Oakview High School",
        location: "Modesto, CA",
        customer: "Swinerton",
      }),
    );
  });

  it("keeps the entered values and names a recovery action when creation fails", async () => {
    const createProject = vi.fn().mockRejectedValue({ message: "The project couldn't be created. Try again." });
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project name/i), "Oakview High School");
    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/try again/i);
    // The form must not clear -- retyping a form after a failed submit is
    // how an estimator loses trust in the first thirty seconds.
    expect(screen.getByLabelText(/project name/i)).toHaveValue("Oakview High School");
  });
});
