// The design's loader: the four squares, centred, no text (design rule 8).
export function Loading({ inline = false }: { inline?: boolean }) {
  return (
    <div className={`loading${inline ? " inline" : ""}`} role="status" aria-label="Loading">
      <div className="spin">
        <svg viewBox="0 0 24 24" width="44" height="44" aria-hidden="true">
          <rect x="1" y="1" width="10" height="10" rx="2.5" stroke="#0a0a0a" fill="#b9ecd0" />
          <rect x="13" y="1" width="10" height="10" rx="2.5" stroke="#0a0a0a" fill="#b9ecd0" />
          <rect x="1" y="13" width="10" height="10" rx="2.5" stroke="#0a0a0a" fill="#b9ecd0" />
          <rect x="13" y="13" width="10" height="10" rx="2.5" stroke="#0a0a0a" fill="#b9ecd0" />
        </svg>
      </div>
    </div>
  );
}
