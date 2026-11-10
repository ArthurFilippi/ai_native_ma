import { TIER_LEGEND, flagText } from "@/lib/constants";
import type { Flag, SourceTier } from "@/lib/contracts";

export function TierChip({ tier }: { tier: SourceTier }) {
  return (
    <span className="chip chip-tier" title={`${TIER_LEGEND[tier].name}: ${TIER_LEGEND[tier].kinds}`}>
      T{tier}
    </span>
  );
}

export function TierLegend({ current }: { current: SourceTier }) {
  return (
    <table className="legend" aria-label="Source reliability tiers">
      <caption>Source reliability tiers (priors by document type, not ground truth)</caption>
      <tbody>
        {([1, 2, 3, 4, 5] as const).map((tier) => (
          <tr key={tier} className={tier === current ? "legend-current" : undefined}>
            <th scope="row">
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
        <span key={flag} className={`chip chip-flag chip-${flag}`}>
          {flagText(flag, date)}
        </span>
      ))}
    </span>
  );
}
