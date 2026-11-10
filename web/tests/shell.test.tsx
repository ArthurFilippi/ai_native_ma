import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "@/components/App";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "#/");
});

describe("design shell", () => {
  it("shows the synthetic data bar and keeps the tab in the URL", async () => {
    render(<App baseUrl="" />);
    expect(screen.getByLabelText("Synthetic data").textContent).toContain("fictional");
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "KPIs" }));
    expect(window.location.hash).toBe("#/kpis");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("KPIs");
  });

  it("lists news events after the connector ran, a denied rumour is never a fact", async () => {
    render(<App baseUrl="" />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Market" }));
    await user.click(await screen.findByRole("button", { name: /Run simulated connector/ }));
    await screen.findByRole("status");
    await user.click(screen.getByRole("tab", { name: "Events" }));
    const table = await screen.findByRole("table", { name: "Market events" });
    expect(within(table).getByText("Denied")).toBeTruthy();
    await user.click(within(table).getByText("Price paid"));
    const detail = screen.getByRole("region", { name: /Event: Orvane Capital, Tessil Works/ });
    expect(within(detail).getByText("Corrected")).toBeTruthy();
    expect(within(detail).getByText("Superseded figure")).toBeTruthy();
  });

  it("opens a buyer card as a window that Escape closes", async () => {
    render(<App baseUrl="" />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Screening" }));
    const table = await screen.findByRole("table", { name: "Screening results" });
    const first = within(table).getAllByRole("button")[0] as HTMLElement;
    await user.click(first);
    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-label")).toMatch(/^Buyer card: /);
    expect(within(dialog).getByText(/coverage/)).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
