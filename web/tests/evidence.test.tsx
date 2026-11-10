import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerCard } from "@/components/AnswerCard";
import { App } from "@/components/App";
import { type Api, ApiError } from "@/lib/api";
import { VALUE_CONTRACT } from "@/lib/constants";
import type { Answer } from "@/lib/contracts";
import contradiction from "@/mock/answer_contradiction.json";
import { MockBackend } from "@/mock/mockApi";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "#/");
});

function setup(makeApi?: (u: string) => Api) {
  const backend = new MockBackend();
  const passage = vi.fn();
  const factory =
    makeApi ??
    ((userId: string): Api => {
      const api = backend.forUser(userId);
      return { ...api, passage: (id) => (passage(id), api.passage(id)) };
    });
  render(<App baseUrl="" makeApi={factory} />);
  return { passage };
}

async function ask(text: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Question about this deal"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByTestId("answer");
  return user;
}

describe("Ask: one card to read the answer, its sources and how sure it is", () => {
  it("shows the answer, the confidence and numbered sources; one click opens the passage", async () => {
    const { passage } = setup();
    const user = await ask("What was FY2024 revenue?");
    const card = screen.getByTestId("answer");
    expect(within(card).getByText("Medium confidence")).toBeTruthy();
    const sources = within(card).getByRole("list", { name: "Sources" });
    const first = within(sources).getAllByRole("button")[0] as HTMLElement;
    expect(first.textContent).toContain("1");
    expect(passage).not.toHaveBeenCalled();
    await user.click(first);
    const mark = await screen.findByTestId("evidence-highlight");
    expect(mark.tagName).toBe("MARK");
    expect(mark.textContent).toBe(contradiction.claims[0]?.citations[0]?.quote);
    expect(passage).toHaveBeenCalledTimes(1);
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("evidence-highlight")).toBeNull();
  });

  it("shows both sides of a disagreement without picking one", async () => {
    setup();
    await ask("What was FY2024 revenue?");
    const block = screen.getByRole("region", { name: /Contradiction: Aurora FY2024 revenue/ });
    expect(within(block).getByText("EUR 182.4m")).toBeTruthy();
    expect(within(block).getByText("about EUR 179m")).toBeTruthy();
    expect(within(block).getByText("Sources disagree. The system does not pick a winner.")).toBeTruthy();
  });

  it("abstains in plain words", async () => {
    setup();
    await ask("CEO compensation?");
    const region = await screen.findByRole("region", { name: "Abstention" });
    expect(region.textContent).toContain("Not found in the sources");
    expect(screen.queryByRole("list", { name: "Sources" })).toBeNull();
  });

  it("carries the value contract as a footer line", async () => {
    setup();
    await screen.findByLabelText("Question about this deal");
    expect(screen.getByText(VALUE_CONTRACT).tagName).toBe("FOOTER");
  });

  it("hides the deal from a user without membership", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Demo user/ }));
    await user.click(await screen.findByRole("option", { name: /Omar Outsider/ }));
    expect(await screen.findByText(/No deal is visible to this user/)).toBeTruthy();
  });

  it("falls back to the quote when the page cannot be loaded", async () => {
    const backend = new MockBackend();
    setup((u) => ({ ...backend.forUser(u), passage: () => Promise.reject(new ApiError(404, "404 Not Found")) }));
    const user = await ask("revenue");
    const sources = screen.getByRole("list", { name: "Sources" });
    await user.click(within(sources).getAllByRole("button")[0] as HTMLElement);
    expect((await screen.findByRole("alert")).textContent).toContain("could not be loaded (404)");
    expect((await screen.findByTestId("evidence-highlight")).textContent).toBe(
      contradiction.claims[0]?.citations[0]?.quote,
    );
  });

  it("marks a degraded answer and a structured record", () => {
    const base = contradiction as unknown as Answer;
    const answer: Answer = {
      ...base,
      degraded: true,
      degraded_reason: "gemini failed on 2 call(s)",
      claims: base.claims.map((c, i) => (i === 0 ? { ...c, origin: "structured" as const } : c)),
    };
    render(<AnswerCard answer={answer} onOpen={() => undefined} activeChunk={null} />);
    expect(screen.getByRole("alert").textContent).toContain("gemini failed");
    expect(screen.getAllByText("Structured record").length).toBe(1);
  });
});

describe("pages", () => {
  it("keeps the page in the URL and shows the data room on Deal", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Deal" }));
    expect(window.location.hash).toBe("#/deal");
    expect(await screen.findByRole("table", { name: "Documents" })).toBeTruthy();
  });

  it("screens buyers, refines in words and flags risks", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Buyers" }));
    await user.click(screen.getByRole("button", { name: "Screen buyers" }));
    const table = await screen.findByRole("table", { name: "Screening results" });
    expect(within(table).getAllByText(/High|Medium|Low/).length).toBeGreaterThan(0);
    expect(within(table).getAllByText("Dealbreaker").length).toBeGreaterThan(0);
    await user.type(screen.getByLabelText("Refine in words"), "only private equity funds");
    await user.click(screen.getByRole("button", { name: "Refine" }));
    expect(await screen.findByText("type: financial")).toBeTruthy();
    const refined = await screen.findByRole("table", { name: "Screening results" });
    expect(within(refined).queryByText("strategic")).toBeNull();
    await user.click(within(refined).getAllByRole("button")[0] as HTMLElement);
    expect((await screen.findByRole("dialog")).getAttribute("aria-label")).toMatch(/^Buyer card: /);
  });

  it("lists news events after an update, a denied rumour is never a fact", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Market" }));
    await user.click(await screen.findByRole("button", { name: "Update news" }));
    const table = await screen.findByRole("table", { name: "Market events" });
    expect(within(table).getByText("Denied")).toBeTruthy();
    expect(within(table).getByText("Corrected")).toBeTruthy();
  });
});
