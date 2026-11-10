import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { VALUE_CONTRACT } from "@/lib/constants";

// Reads the Python source of truth and compares the concatenated string literals.
function pythonValueContract(): string {
  const source = readFileSync("../src/ainma/contracts.py", "utf-8");
  const block = /VALUE_CONTRACT = \(([\s\S]*?)\n\)/.exec(source);
  if (!block?.[1]) throw new Error("VALUE_CONTRACT not found in contracts.py");
  const parts = [...block[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1] ?? "");
  return parts.join("");
}

describe("value contract", () => {
  it("equals VALUE_CONTRACT in src/ainma/contracts.py", () => {
    expect(VALUE_CONTRACT).toBe(pythonValueContract());
  });

  it("is the sentence of the specification", () => {
    expect(VALUE_CONTRACT).toBe(
      "I summarise the evidence clearly and show you the sources, so that you can examine them and make informed decisions.",
    );
  });
});
