import { useEffect, useRef } from "react";

export default function ConfirmDialog({ title, body, confirmLabel, busy, onCancel, onConfirm }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => d && d.open && d.close();
  }, []);
  return (
    <dialog ref={ref} className="dialog" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h3>{title}</h3>
      <p>{body}</p>
      <p className="muted small">Your name and this action are recorded in the audit log.</p>
      <div className="dialog-actions">
        <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn primary" onClick={onConfirm} disabled={busy} autoFocus>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
