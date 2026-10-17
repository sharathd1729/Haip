import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ConceptView } from "./ConceptView";
import { CONCEPTS, SCREENS } from "./concepts";

afterEach(cleanup);

// Every concept must draw every screen with the shared demo content, so the lab always compares like with like.
describe("design lab concepts", () => {
  for (const c of CONCEPTS) {
    for (const s of SCREENS) {
      it(`${c.name}: ${s.label} renders its content`, () => {
        render(<ConceptView concept={c.id} initialScreen={s.id} />);
        if (s.id === "home") expect(screen.getAllByText(/₹3,42,500|₹3\.42L/).length).toBeGreaterThan(0);
        if (s.id === "inbox") expect(screen.getAllByText("Priya Nair").length).toBeGreaterThan(0);
        if (s.id === "leads") expect(screen.getAllByText("Meera Reddy").length).toBeGreaterThan(0);
        if (s.id === "calendar") expect(screen.getAllByText(/Vikram/).length).toBeGreaterThan(0);
      });
    }
  }

  it("switches screens from the concept's own navigation", () => {
    render(<ConceptView concept="calm" initialScreen="home" />);
    fireEvent.click(screen.getAllByRole("button", { name: /^Inbox/ })[0]);
    expect(screen.getAllByText("Priya Nair").length).toBeGreaterThan(0);
  });
});
