// Phase 1.5 — masters API client functions.
//
// Covers the contract the new MastersPage and useMasters hook
// depend on. Real HTTP is mocked via vi.spyOn(window, 'fetch') so
// tests assert URL templating + headers without spinning up the
// backend.

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  listMasters,
  uploadMaster,
  activateMaster,
  deleteMaster,
  listLayouts,
  updateLayout,
  setLayoutDefault,
} from "../src/api/masters.js";

describe("masters api client", () => {
  let fetchSpy;

  beforeEach(() => {
    fetchSpy = vi.spyOn(window, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ masters: [], active_master_id: null }),
      text: async () => "",
    });
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("listMasters GETs the project-scoped URL with auth and returns both list and active id", async () => {
    const out = await listMasters("token-x", "proj-1");
    // Phase 2.0: contract is { masters, activeMasterId } — the hook
    // pins the active card based on activeMasterId, not on local state.
    expect(out).toEqual({ masters: [], activeMasterId: null });
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/projects\/proj-1\/masters$/);
    expect(opts.method ?? "GET").toBe("GET");
    expect(opts.headers.Authorization).toBe("Bearer token-x");
  });

  it("listMasters propagates active_master_id from server", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        masters: [{ id: "m1" }, { id: "m2" }],
        active_master_id: "m2",
      }),
      text: async () => "",
    });
    const out = await listMasters("tok", "proj");
    expect(out.masters).toHaveLength(2);
    expect(out.activeMasterId).toBe("m2");
  });

  it("uploadMaster POSTs multipart to /agent/masters/upload", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ master: { id: "m1" }, summary: {} }),
      text: async () => "",
    });
    const file = new File([new Uint8Array([1, 2, 3])], "t.pptx", {
      type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    });
    const out = await uploadMaster("tok", "proj-1", file);
    expect(out.master.id).toBe("m1");

    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/agent\/masters\/upload$/);
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
    expect(opts.body.get("project_id")).toBe("proj-1");
    // jsdom returns a Blob/File for FormData.get(); we just want
    // the file slot populated with the right name.
    expect(opts.body.get("file").name).toBe("t.pptx");
    // Multipart MUST NOT set a hard-coded Content-Type — the browser
    // adds the boundary automatically. Only Authorization should
    // appear in the headers.
    expect(opts.headers["Content-Type"]).toBeUndefined();
    expect(opts.headers.Authorization).toBe("Bearer tok");
  });

  it("activateMaster POSTs to /masters/{id}/activate", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ active_master_id: "m1" }),
      text: async () => "",
    });
    const out = await activateMaster("tok", "m1");
    expect(out.active_master_id).toBe("m1");
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/masters\/m1\/activate$/);
    expect(opts.method).toBe("POST");
  });

  it("deleteMaster DELETEs /masters/{id}", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({}),
      text: async () => "",
    });
    await deleteMaster("tok", "m1");
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/masters\/m1$/);
    expect(opts.method).toBe("DELETE");
  });

  // Phase 2.4 — curation surface.

  it("listLayouts GETs /masters/{id}/layouts and unwraps the array", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        layouts: [
          { id: "L1", name: "Title Slide", auto_kind: "title" },
          { id: "L2", name: "Two Columns", auto_kind: "two_column" },
        ],
      }),
      text: async () => "",
    });
    const out = await listLayouts("tok", "m1");
    expect(out).toHaveLength(2);
    expect(out[0].id).toBe("L1");
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/masters\/m1\/layouts$/);
    expect(opts.headers.Authorization).toBe("Bearer tok");
  });

  it("updateLayout PATCHes /master_layouts/{id} with the partial payload", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ id: "L1", user_kind: "cover", enabled: false }),
      text: async () => "",
    });
    const out = await updateLayout("tok", "L1", {
      user_kind: "cover",
      enabled: false,
    });
    expect(out.user_kind).toBe("cover");
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/master_layouts\/L1$/);
    expect(opts.method).toBe("PATCH");
    expect(JSON.parse(opts.body)).toEqual({
      user_kind: "cover",
      enabled: false,
    });
  });

  it("setLayoutDefault POSTs /master_layouts/{id}/default", async () => {
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ id: "L1", is_default: true }),
      text: async () => "",
    });
    const out = await setLayoutDefault("tok", "L1");
    expect(out.is_default).toBe(true);
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/master_layouts\/L1\/default$/);
    expect(opts.method).toBe("POST");
  });
});
