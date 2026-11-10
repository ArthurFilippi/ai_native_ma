import { useEffect, useId, useRef, useState } from "react";

export interface Option {
  value: string;
  label: string;
  sub?: string;
}

// The design's dropdown (.dd): a button that opens a list of mono rows, a dot marks the selected
// one. Native selects are not used for visible choices (design/DESIGN.md, section 8).
export function Dropdown({
  label,
  value,
  options,
  onChange,
  small = false,
}: {
  label: string;
  value: string;
  options: readonly Option[];
  onChange: (value: string) => void;
  small?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const listId = useId();
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={root} className={`dd${small ? " sm" : ""}${open ? " open" : ""} dd-anchor`}>
      <button
        type="button"
        className="dd-btn"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="dd-text">
          <b>{current?.label ?? value}</b>
        </span>
        <span className="dd-caret" />
      </button>
      {open && (
        <ul id={listId} className="dd-list dd-float" role="listbox" aria-label={label}>
          {options.map((option) => (
            <li
              key={option.value}
              role="option"
              aria-selected={option.value === value}
              className={`dd-opt${option.value === value ? " sel" : ""}`}
              tabIndex={0}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onChange(option.value);
                  setOpen(false);
                }
              }}
            >
              <span className="dd-mk" />
              <b>{option.label}</b>
              {option.sub && <span className="dd-sub">{option.sub}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
