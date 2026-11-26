import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";

const res = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  beforeEach(() => useAuth.setState({ accessToken: "old", refreshToken: "r1" }));
  afterEach(() => vi.restoreAllMocks());

  it("refreshes once on 401 and retries with the new token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(res(401, { error: { code: "unauthorized", message: "expired" } }))
      .mockResolvedValueOnce(res(200, { access_token: "new", refresh_token: "r2", token_type: "bearer", expires_in: 900 }))
      .mockResolvedValueOnce(res(200, { ok: true }));
    await expect(api("/api/thing")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryHeaders = fetchMock.mock.calls[2]![1]!.headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new");
    expect(useAuth.getState().refreshToken).toBe("r2");
  });

  it("clears the session when refresh fails and surfaces API errors", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(res(401, { error: { code: "unauthorized", message: "expired" } }))
      .mockResolvedValueOnce(res(401, { error: { code: "unauthorized", message: "bad refresh" } }));
    await expect(api("/api/thing")).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    expect(useAuth.getState().accessToken).toBeNull();
  });

  it("maps error bodies to ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(res(409, { error: { code: "conflict", message: "exists" } }));
    const err = (await api("/api/x", { method: "POST", body: "{}" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("exists");
  });
});
