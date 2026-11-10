import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AnswerView } from "@/components/AnswerView";
import type { Answer } from "@/lib/contracts";
import contradiction from "@/mock/answer_contradiction.json";

afterEach(cleanup);

it("shows a degraded answer and names the judge model", () => {
  const answer = {
    ...(contradiction as unknown as Answer),
    degraded: true,
    degraded_reason: "gemini failed on 2 call(s); the offline mock answered them.",
    trace: {
      ...(contradiction as unknown as Answer).trace,
      judge_provider: "gemini",
      judge_model: "gemini-2.5-pro",
    },
  };
  render(<AnswerView answer={answer} onOpen={() => undefined} activeChunk={null} />);
  expect(screen.getByRole("alert").textContent).toContain("gemini failed");
  expect(screen.getByText(/gemini-2\.5-pro/)).toBeTruthy();
});

it("marks a claim that comes from the structured fact base", () => {
  const base = contradiction as unknown as Answer;
  const answer = {
    ...base,
    claims: base.claims.map((c, i) => (i === 0 ? { ...c, origin: "structured" as const } : c)),
  };
  render(<AnswerView answer={answer} onOpen={() => undefined} activeChunk={null} />);
  expect(screen.getAllByText("Structured record").length).toBe(1);
});
