// Brand-font reconciliation: which referenced fonts are missing from
// the bundle? Locks in the system-font allowlist (we don't ask users
// to upload Arial / Calibri) and case-insensitive matching.

import { describe, it, expect } from "vitest";
import {
  computeMissingBrandFonts,
  isSystemFontName,
} from "../src/utils/brandFonts.js";

describe("isSystemFontName", () => {
  it("matches common system fonts case-insensitively", () => {
    expect(isSystemFontName("Arial")).toBe(true);
    expect(isSystemFontName("arial")).toBe(true);
    expect(isSystemFontName("Calibri")).toBe(true);
    expect(isSystemFontName("Times New Roman")).toBe(true);
    expect(isSystemFontName("Georgia")).toBe(true);
  });

  it("rejects brand fonts", () => {
    expect(isSystemFontName("STC Forward")).toBe(false);
    expect(isSystemFontName("Fund Light")).toBe(false);
    expect(isSystemFontName("PwC Helvetica Neue")).toBe(false);
  });

  it("treats whitespace and case forgivingly", () => {
    expect(isSystemFontName("  Arial  ")).toBe(true);
    expect(isSystemFontName("ARIAL")).toBe(true);
  });

  it("returns false for empty / null", () => {
    expect(isSystemFontName("")).toBe(false);
    expect(isSystemFontName(null)).toBe(false);
    expect(isSystemFontName(undefined)).toBe(false);
  });
});

describe("computeMissingBrandFonts", () => {
  it("returns empty when no fonts referenced", () => {
    expect(computeMissingBrandFonts([], [])).toEqual([]);
    expect(computeMissingBrandFonts(null, null)).toEqual([]);
  });

  it("filters out system fonts even when not bundled", () => {
    expect(
      computeMissingBrandFonts(["Arial", "Calibri", "Georgia"], []),
    ).toEqual([]);
  });

  it("flags brand fonts that aren't bundled", () => {
    const result = computeMissingBrandFonts(
      ["Arial", "STC Forward", "Fund Light"],
      [],
    );
    expect(result).toEqual(["STC Forward", "Fund Light"]);
  });

  it("excludes brand fonts that ARE bundled", () => {
    const result = computeMissingBrandFonts(
      ["STC Forward", "Fund Light"],
      [{ family: "STC Forward", weight: 700 }],
    );
    expect(result).toEqual(["Fund Light"]);
  });

  it("matches family case-insensitively", () => {
    const result = computeMissingBrandFonts(
      ["STC Forward"],
      [{ family: "stc forward", weight: 400 }],
    );
    expect(result).toEqual([]);
  });

  it("returns empty when every brand font is bundled", () => {
    const result = computeMissingBrandFonts(
      ["Arial", "STC Forward", "Fund Light"],
      [
        { family: "STC Forward", weight: 700 },
        { family: "Fund Light", weight: 300 },
      ],
    );
    expect(result).toEqual([]);
  });

  it("ignores blank-string referenced fonts", () => {
    const result = computeMissingBrandFonts(
      ["", "STC Forward", null],
      [],
    );
    expect(result).toEqual(["STC Forward"]);
  });
});
