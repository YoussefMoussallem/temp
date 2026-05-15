// Smoke test — confirms vitest is wired and jsdom is available.

import { describe, it, expect } from "vitest";

describe("vitest harness", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });

  it("has a DOM", () => {
    expect(typeof window).toBe("object");
    expect(typeof document).toBe("object");
  });
});
