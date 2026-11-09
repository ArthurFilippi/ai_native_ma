import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "@/components/App";
import { type Api, ApiError } from "@/lib/api";
import { VALUE_CONTRACT } from "@/lib/constants";
import contradiction from "@/mock/answer_contradiction.json";
import { MockBackend } from "@/mock/mockApi";

afterEach(cleanup);

// No jest-dom here: visible means attached, with no hidden or display:none ancestor.
function visible(element: HTMLElement): boolean {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    if (node.hidden || getComputedStyle(node).display === "none") return false;
  }
  return element.isConnected;
}

// The browser level check of the principle: ask, click one citation, see the highlighted span.
function setup() {
  const backend = new MockBackend();
  const passage = vi.fn();
  const makeApi = (userId: string): Api => {
    const api = backend.forUser(userId);
    return {
      ...api,
      passage: (chunkId) => {
        passage(chunkId);
        return api.passage(chunkId);
      },
    };
  };
  render(<App baseUrl="" makeApi={makeApi} />);
  return { passage };
}

async function askRevenue() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Question about this deal"), "What was FY2024 revenue?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await screen.findByTestId("answer");
  return user;
}

describe("answer and evidence screen", () => {
  it("shows the highlighted span after exactly one click on a citation", async () => {
    const { passage } = setup();
    const user = await askRevenue();
    expect(passage).not.toHaveBeenCalled();
    expect(screen.queryByTestId("evidence-highlight")).toBeNull();

    const claim = contradiction.claims[0];
    const quote = claim?.citations[0]?.quote ?? "";
    const firstClaim = document.getElementById("claim-c1");
    if (!firstClaim) throw new Error("first claim not rendered");
    await user.click(within(firstClaim).getAllByRole("button")[0] as HTMLElement);

    const mark = await screen.findByTestId("evidence-highlight");
    expect(mark.tagName).toBe("MARK");
    expect(mark.textContent).toBe(quote);
    expect(visible(mark)).toBe(true);
    expect(passage).toHaveBeenCalledTimes(1);

    const panel = screen.getByRole("complementary", { name: "Evidence panel" });
    expect(visible(within(panel).getByText("Project Aurora, Confidential Information Memorandum"))).toBe(true);
    expect(visible(within(panel).getByText("Source reliability tiers (priors by document type, not ground truth)"))).toBe(true);
    expect(visible(within(panel).getByText(/Exact phrase match on revenue/))).toBe(true);
  });

  it("shows both sides of a contradiction and the fixed note", async () => {
    setup();
    await askRevenue();
    const block = screen.getByRole("region", { name: /Contradiction: Aurora FY2024 revenue/ });
    expect(visible(within(block).getByText("EUR 182.4m"))).toBe(true);
    expect(visible(within(block).getByText("about EUR 179m"))).toBe(true);
    expect(visible(within(block).getByText("Sources disagree. The system does not pick a winner."))).toBe(true);
  });

  it("distinguishes sourced, inferred and missing claims without colour", async () => {
    setup();
    await askRevenue();
    expect(screen.getAllByText("Sourced").length).toBeGreaterThan(0);
    expect(visible(screen.getByText("System deduction"))).toBe(true);
    expect(screen.getAllByText("Not established by the sources").length).toBeGreaterThan(0);
    expect(document.querySelector(".claim-inferred")).not.toBeNull();
    expect(screen.getAllByText("Single low-tier source").length).toBeGreaterThan(0);
  });

  it("abstains with a reason and no claim rows", async () => {
    setup();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Question about this deal"), "CEO compensation?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByRole("region", { name: "Abstention" });
    expect(visible(screen.getByText("No retrieved passage scored above the support threshold."))).toBe(true);
    expect(screen.queryByRole("region", { name: "Claims" })).toBeNull();
  });

  it("carries the value contract as a footer line", async () => {
    setup();
    await screen.findByLabelText("Question about this deal");
    expect(screen.getByText(VALUE_CONTRACT).tagName).toBe("FOOTER");
  });

  it("hides the deal from a user without membership", async () => {
    setup();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(/Demo user/), "u_outsider");
    expect(visible(await screen.findByText(/No deal is visible to this user/))).toBe(true);
  });
});

describe("evidence panel when the page cannot be loaded", () => {
  it("falls back to the cited quote and says so", async () => {
    const backend = new MockBackend();
    const makeApi = (userId: string): Api => ({
      ...backend.forUser(userId),
      passage: () => Promise.reject(new ApiError(404, "404 Not Found")),
    });
    render(<App baseUrl="" makeApi={makeApi} />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Question about this deal"), "revenue");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByTestId("answer");
    const firstClaim = document.getElementById("claim-c1");
    if (!firstClaim) throw new Error("first claim not rendered");
    await user.click(within(firstClaim).getAllByRole("button")[0] as HTMLElement);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("could not be loaded (404)");
    expect((await screen.findByTestId("evidence-highlight")).textContent).toBe(
      contradiction.claims[0]?.citations[0]?.quote,
    );
  });
});
