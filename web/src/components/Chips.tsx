import { TIER_LEGEND, flagText } from "@/lib/constants";
import type { DocStatus, Flag, SourceTier } from "@/lib/contracts";

// Chips are the design's `.st` pills: colour is meaning (ok mint, warn butter, bad rose, sky info),
// one wording per state everywhere.
const FLAG_TONE: Record<Flag, string> = {
  stale: "warn",
  superseded: "warn",
  withdrawn: "bad",
  single_low_tier_source: "warn",
  contradicted: "bad",
  unverified: "bad",
};

const STATUS_TONE: Record<DocStatus, string> = { current: "ok", superseded: "warn", withdrawn: "bad" };

export function TierChip({ tier }: { tier: SourceTier }) {
  return (
    <span className="st chip-tier" title={`${TIER_LEGEND[tier].name}: ${TIER_LEGEND[tier].kinds}`}>
      T{tier}
    </span>
  );
}

export function StatusChip({ status }: { status: DocStatus }) {
  return <span className={`st ${STATUS_TONE[status]}`}>{status}</span>;
}

export function TierLegend({ current }: { current: SourceTier }) {
  return (
    <table className="tbl tier-legend" aria-label="Source reliability tiers">
      <caption className="lab">Source reliability tiers (priors by document type, not ground truth)</caption>
      <tbody>
        {([1, 2, 3, 4, 5] as const).map((tier) => (
          <tr key={tier} className={tier === current ? "sel" : undefined}>
            <th scope="row" className="mono">
              T{tier}
              {tier === current ? " (this source)" : ""}
            </th>
            <td>{TIER_LEGEND[tier].kinds}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FlagChips({ flags, date }: { flags: readonly Flag[]; date: string | null }) {
  if (flags.length === 0) return null;
  return (
    <span className="flags">
      {flags.map((flag) => (
        <span key={flag} className={`st ${FLAG_TONE[flag]} chip-${flag}`}>
          {flagText(flag, date)}
        </span>
      ))}
    </span>
  );
}
