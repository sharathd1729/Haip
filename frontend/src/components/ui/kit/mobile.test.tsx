import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Phone } from "@/lib/icons";
import { BottomSheet, ChipRow, CompactRow, Fab, OneLineSummary, RowAction, RowList, SWIPE_CLOSE_PX } from "@/components/ui/kit";
import { shortAgo, waitText } from "@/lib/waitText";

vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));

// jsdom has no PointerEvent, so fireEvent.pointer* would drop clientY. A MouseEvent carries it.
if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = class extends MouseEvent {} as typeof MouseEvent;
}

beforeEach(() => cleanup());

describe("CompactRow", () => {
  it("shows who, why and how late, and its actions do not open the row", async () => {
    const open = vi.fn();
    const call = vi.fn();
    render(<RowList><CompactRow title="Ravi · Kerala" subtitle="Asked for a call back" meta="2d late" metaTone="danger" onClick={open}
      actions={<RowAction icon={Phone} label="Call Ravi" primary onClick={call} />} /></RowList>);
    expect(screen.getByText("Ravi · Kerala")).toBeTruthy();
    expect(screen.getByText("Asked for a call back")).toBeTruthy();
    expect(screen.getByText("2d late").className).toContain("danger");
    await userEvent.click(screen.getByRole("button", { name: "Call Ravi" }));
    expect(call).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Ravi · Kerala"));
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("a row action is a 44px target and the primary one uses the action colour", () => {
    render(<RowAction icon={Phone} label="Call" primary onClick={() => undefined} />);
    const b = screen.getByRole("button", { name: "Call" });
    expect(b.className).toContain("size-11");
    expect(b.className).toContain("--haip-action");
  });

  it("is a link when given an href", () => {
    render(<RowList><CompactRow title="Anita" href="/dashboard/bookings/b1" /></RowList>);
    expect(screen.getByRole("link").getAttribute("href")).toBe("/dashboard/bookings/b1");
  });
});

describe("ChipRow", () => {
  it("marks the chosen chip, shows counts and the Filters button with how many are on", async () => {
    const pick = vi.fn();
    const filters = vi.fn();
    render(<ChipRow label="Show" value="mine" onChange={pick} onFilters={filters} filterCount={2}
      items={[{ value: "mine", label: "Mine", count: 7 }, { value: "team", label: "Team", count: 31 }]} />);
    expect(screen.getByRole("button", { name: /Mine/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /Team/ }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("31")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Team/ }));
    expect(pick).toHaveBeenCalledWith("team");
    await userEvent.click(screen.getByRole("button", { name: "Filters, 2 on" }));
    expect(filters).toHaveBeenCalled();
  });
});

describe("BottomSheet", () => {
  it("opens with its title and closes on Esc and on the close button", async () => {
    const change = vi.fn();
    render(<BottomSheet open onOpenChange={change} title="Anita · Coorg">Body text</BottomSheet>);
    expect(await screen.findByText("Anita · Coorg")).toBeTruthy();
    expect(screen.getByText("Body text")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(change).toHaveBeenCalledWith(false));
    change.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(change).toHaveBeenCalledWith(false));
  });

  it("closes on a long swipe down and stays open on a short one", async () => {
    const change = vi.fn();
    render(<BottomSheet open onOpenChange={change} title="Filters">x</BottomSheet>);
    const handle = await screen.findByTestId("bottom-sheet-handle");
    fireEvent.pointerDown(handle, { clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(handle, { clientY: 130, pointerId: 1 });
    expect(change).not.toHaveBeenCalled();
    fireEvent.pointerDown(handle, { clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientY: 100 + SWIPE_CLOSE_PX + 10, pointerId: 1 });
    fireEvent.pointerUp(handle, { clientY: 100 + SWIPE_CLOSE_PX + 10, pointerId: 1 });
    expect(change).toHaveBeenCalledWith(false);
  });

  it("renders nothing while closed", () => {
    render(<BottomSheet open={false} onOpenChange={() => undefined} title="Hidden">x</BottomSheet>);
    expect(screen.queryByText("Hidden")).toBeNull();
  });
});

describe("OneLineSummary", () => {
  it("offers 'more' only for a long note and toggles it", async () => {
    const { rerender } = render(<OneLineSummary text="Wants Coorg 3 days" />);
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<OneLineSummary text="Wants a Goa trip for 4 adults on 26 Nov; Goa is not offered, so suggest Western Ghats to the Sea instead" />);
    const more = screen.getByRole("button", { name: "more" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "less" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("renders nothing without text", () => {
    const { container } = render(<OneLineSummary text="  " />);
    expect(container.textContent).toBe("");
  });
});

describe("Fab", () => {
  it("is a labelled button (or link) that is hidden from md up", async () => {
    const add = vi.fn();
    render(<Fab label="New lead" onClick={add} />);
    const b = screen.getByRole("button", { name: "New lead" });
    expect(b.className).toContain("md:hidden");
    await userEvent.click(b);
    expect(add).toHaveBeenCalled();
  });
});

describe("waitText", () => {
  const now = Date.parse("2026-10-24T12:00:00Z");
  const before = (min: number) => new Date(now - min * 60_000).toISOString();
  it("says late only past the target, and due for a time ahead", () => {
    expect(waitText(before(5), "fresh", now)).toBe("5m");
    expect(waitText(before(3 * 1440), "urgent", now)).toBe("3d late");
    expect(waitText(before(300), "late", now)).toBe("5h late");
    expect(waitText(new Date(now + 20 * 60_000).toISOString(), "fresh", now)).toBe("due in 20m");
    expect(waitText(before(9000), "stale", now)).toBe("gone cold");
    expect(shortAgo(null)).toBe("");
  });
});
