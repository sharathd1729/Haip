import { describe, expect, it } from "vitest";
import { buildComponents, formFromTemplate, urlExample, type Template } from "./templateModel";

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
