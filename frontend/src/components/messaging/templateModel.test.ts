import { describe, expect, it } from "vitest";
import { buildComponents, emptyForm, formFromTemplate, localProblems, newButton, newCard, urlExample, type Template } from "./templateModel";

const balanceDue: Template = {
  id: "t1", name: "ratha_balance_due_v1", language: "en", category: "UTILITY", status: "draft",
  meta_template_id: null, rejection_reason: null, header_media_key: null, header_media_url: null, created_at: null,
  components: [
    { type: "BODY", text: "Hi {{1}}", example: { body_text: [["Kiran"]] } },
    { type: "BUTTONS", buttons: [{ type: "URL", text: "Pay balance", url: "https://rzp.io/{{1}}", example: ["https://rzp.io/i/AbC123xyz"] }] },
  ],
};

describe("dynamic link buttons survive the editor", () => {
  it("keeps the sample link of a {{1}} button through open and save", () => {
    const comps = buildComponents(formFromTemplate(balanceDue));
    const buttons = comps.find(c => c.type === "BUTTONS")!.buttons!;
    expect(buttons[0]).toEqual({ type: "URL", text: "Pay balance", url: "https://rzp.io/{{1}}", example: ["https://rzp.io/i/AbC123xyz"] });
  });
  it("adds a sample for a new {{1}} link and none for a fixed link", () => {
    expect(urlExample({ url: "https://ratha.in/pay/{{1}}", urlExample: "" })).toEqual({ example: ["https://ratha.in/pay/example"] });
    expect(urlExample({ url: "https://ratha.in", urlExample: "" })).toEqual({});
  });
});

const TEMPLATE_BASE: Template = { ...balanceDue, category: "MARKETING", components: [] };

describe("marketing formats", () => {
  it("round-trips a limited-time offer with an offer code", () => {
    const form = { ...emptyForm(), name: "diwali", body: "Diwali at Ratha", format: "offer" as const, offerText: "Ends soon", offerCountdown: true,
      buttons: [{ ...newButton("COPY_CODE"), code: "DIWALI20" }, { ...newButton("URL"), text: "Book", url: "https://r.example/b" }] };
    const comps = buildComponents(form);
    expect(comps.find(c => c.type === "LIMITED_TIME_OFFER")).toEqual({ type: "LIMITED_TIME_OFFER", limited_time_offer: { text: "Ends soon", has_expiration: true } });
    expect(comps.find(c => c.type === "BUTTONS")?.buttons?.[0]).toEqual({ type: "COPY_CODE", text: "Copy offer code", example: "DIWALI20" });
    const back = formFromTemplate({ ...TEMPLATE_BASE, components: comps });
    expect(back.format).toBe("offer");
    expect(back.buttons[0].code).toBe("DIWALI20");
    expect(localProblems(back)).toEqual([]);
  });

  it("builds a carousel with each card's stored file", () => {
    const card = (n: number) => ({ ...newCard(), media: { key: `t/wa_templates/${n}.jpg`, handle: `h${n}`, previewUrl: null, fileName: "x" }, body: `Route ${n}`,
      buttons: [{ ...newButton("URL"), text: "View", url: "https://r.example" }] });
    const form = { ...emptyForm(), name: "routes", body: "Pick a route", format: "carousel" as const, cards: [card(1), card(2)] };
    const comps = buildComponents(form);
    expect(comps.map(c => c.type)).toEqual(["BODY", "CAROUSEL"]);
    expect(comps[1].cards?.[1].components[0]).toMatchObject({ format: "IMAGE", media_key: "t/wa_templates/2.jpg", example: { header_handle: ["h2"] } });
    expect(localProblems(form)).toEqual([]);
    expect(formFromTemplate({ ...TEMPLATE_BASE, components: comps }).cards).toHaveLength(2);
  });
});
