import { type ReactNode, useEffect } from "react";

// A panel that slides over the right of the page: the source, a buyer. Escape or the backdrop
// closes it; the page under it keeps its scroll and its state.
export function Drawer({
  children,
  onClose,
  label,
}: {
  children: ReactNode;
  onClose: () => void;
  label: string;
}) {
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);
  return (
    <div className="drawer-host">
      <div className="drawer-back" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </div>
  );
}
