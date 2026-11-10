import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createHttpApi } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("http api client", () => {
  it("sends the demo user header and labels the source as the real API", async () => {
    const fetchMock = stubFetch(
      new Response(JSON.stringify({ deal_id: "deal_aurora", ingested: 0 })),
    );
    const api = createHttpApi("http://localhost:8000/", "u_analyst");
    const served = await api.runMarketIntel("deal_aurora");
    expect(served.backend).toBe("real");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/deals/deal_aurora/market-intel/run");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-User-Id"]).toBe("u_analyst");
  });

  it("asks for the page text of a passage with one request", async () => {
    const fetchMock = stubFetch(new Response("{}"));
    await createHttpApi("http://x", "u_lead").passage("doc_cim_p2_00");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://x/passages/doc_cim_p2_00?page=true");
  });

  it("turns a 404 into an ApiError", async () => {
    stubFetch(new Response("{}", { status: 404, statusText: "Not Found" }));
    const failure = await createHttpApi("http://x", "u_outsider").deals().catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
  });
});
