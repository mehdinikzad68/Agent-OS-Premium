// Connection type picker — the non-drag connection flow
// (and the multi-type drop case). Keyboard accessible:
// the first type is focused on open, Escape cancels.
import { useEffect, useRef } from "react";
import { Cable } from "lucide-react";

export default function ConnectionPicker({ t, title, types, onConfirm, onCancel }) {
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="glass rise w-[230px] p-3" role="dialog" aria-label={title}>
      <div className="mb-2 text-[13px] text-[var(--mu)]">{title}</div>
      <div className="flex flex-col gap-1.5">
        {types.map((tp, i) => (
          <button
            key={tp.type}
            ref={i === 0 ? firstRef : null}
            type="button"
            onClick={() => onConfirm(tp.type)}
            className="chip flex items-center justify-start gap-2"
            data-on={false}
          >
            <Cable size={13} className="text-[var(--sun)]" />
            <span>{tp.label}</span>
          </button>
        ))}
        <button
          type="button"
          onClick={onCancel}
          className="chip justify-center text-[var(--mu)]"
        >
          {t.cancel}
        </button>
      </div>
    </div>
  );
}
