// Smoke test — confirms vitest is wired and jsdom is available.
// Component / Context tests land alongside the features they cover.

import { describe, it, expect } from "vitest";

describe("vitest harness", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });

  it("has a DOM", () => {
    // jsdom should give us window/document; failing here means the
    // vitest config didn't apply environment:'jsdom'.
    expect(typeof window).toBe("object");
    expect(typeof document).toBe("object");
  });
});
