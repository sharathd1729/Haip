import { describe, expect, it } from "vitest";
import { failureStep } from "./deliveryFailure";

describe("failureStep", () => {
  it("never offers Retry for a number that isn't on WhatsApp", () => {
    expect(failureStep("This number isn't on WhatsApp, or it can't receive messages from businesses. Call the guest. (Meta 131026)")).toBe("none");
  });
  it("offers a template when the WhatsApp window closed", () => {
    expect(failureStep("The guest's 24-hour WhatsApp window is closed, so only an approved template can go. (Meta 131047)")).toBe("template");
  });
  it("offers WhatsApp when Instagram's window closed", () => {
    expect(failureStep("(#10) This message is sent outside of allowed window.", { channel: "instagram" })).toBe("whatsapp");
  });
  it("a template is re-sent from the picker, not retried", () => {
    expect(failureStep("Max retries exceeded", { isTemplate: true })).toBe("none");
  });
  it("keeps Retry for a passing error", () => {
    expect(failureStep("Max retries exceeded")).toBe("retry");
    expect(failureStep(null)).toBe("retry");
  });
});
