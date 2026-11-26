import { describe, expect, it } from "vitest";
import { attachmentProblem, formatBytes } from "./attachment";

const MB = 1024 * 1024;

describe("attachmentProblem", () => {
  it("takes WhatsApp's types within their limits", () => {
    expect(attachmentProblem({ type: "image/jpeg", size: 5 * MB })).toBeNull();
    expect(attachmentProblem({ type: "video/mp4", size: 16 * MB })).toBeNull();
    expect(attachmentProblem({ type: "audio/ogg", size: MB })).toBeNull();
    expect(attachmentProblem({ type: "application/pdf", size: 100 * MB })).toBeNull();
  });

  it("says the limit when a file is too big", () => {
    expect(attachmentProblem({ type: "image/png", size: 5 * MB + 1 })).toMatch(/Photos can be up to 5 MB/);
    expect(attachmentProblem({ type: "video/mp4", size: 17 * MB })).toMatch(/16 MB.*17\.0 MB/);
  });

  it("refuses other types", () => {
    expect(attachmentProblem({ type: "image/gif", size: 10 })).toMatch(/JPEG or PNG/);
    expect(attachmentProblem({ type: "", size: 10 })).not.toBeNull();
  });
});

describe("formatBytes", () => {
  it("reads like a person would say it", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3.25 * MB)).toBe("3.3 MB");
  });
});
