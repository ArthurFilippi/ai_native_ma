// Refresh the committed mock payloads from their sources (run from web/ with `npm run sync-mock`).
// A test fails when a copy drifts from its source.
import { copyFileSync } from "node:fs";

const FROM_FIXTURES = ["answer_contradiction.json", "answer_abstention.json", "buyer_card.json"];
const FROM_API_EXAMPLES = ["screening_result.json", "kpis.json"];

for (const name of FROM_FIXTURES) copyFileSync(`../tests/fixtures/${name}`, `src/mock/${name}`);
for (const name of FROM_API_EXAMPLES) {
  copyFileSync(`../src/ainma/api/examples/${name}`, `src/mock/${name}`);
}
