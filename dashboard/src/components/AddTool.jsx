// Minified name in bundle: gx.
import { useEffect, useRef, useState } from "react";
import { Cable, X } from "lucide-react";
import { PALETTE, STATUS_COLOR } from "../scene/colors.js";

export default function AddTool({ t, rtl, agents, onCancel, onAdd }) {
  const parents = agents.filter((a) => a.id !== "hermes" && !a.parent);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [parent, setParent] = useState("hermes");
  const [status, setStatus] = useState("running");
  const [color, setColor] = useState(0);
  const nameRef = useRef();

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const submit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    const id = name.trim().toLowerCase().replace(/[^a-z0-9\u0600-\u06ff]+/g, "-") + "-" + Date.now().toString(36).slice(-4);
    onAdd({
      id,
      name: name.trim(),
      sub: { en: role.trim() || "Tool", fa: role.trim() || "ابزار" },
      status,
      tok: "0",
      load: status === "running" ? 12 : 0,
      seen: new Date().toTimeString().slice(0, 8),
      body: PALETTE[color],
      parent: parent === "hermes" ? null : parent,
      custom: true,
    });
  };

  return (
    <div className="absolute inset-0 z-30 grid place-items-center bg-[rgba(1,5,10,.6)] p-4 backdrop-blur-[2px]" onClick={onCancel}>
      <form
        dir={rtl ? "rtl" : "ltr"}
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="rise glass w-full max-w-[420px] p-5"
        style={{ borderColor: "rgba(56,232,255,.3)" }}
      >
        <div className="flex items-start gap-3">
          <span
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full"
            style={{ border: `2px dashed ${PALETTE[color]}`, boxShadow: `0 0 18px ${PALETTE[color]}88, inset 0 0 12px ${PALETTE[color]}66` }}
          >
            <Cable size={16} color={PALETTE[color]} />
          </span>
          <div>
            <h3 className="disp text-[22px] leading-none">{t.addTitle}</h3>
            <div className="mt-1 text-[14px] text-[var(--mu)]">{t.addSub}</div>
          </div>
          <button type="button" onClick={onCancel} aria-label="Close" className="ms-auto text-[var(--mu)] hover:text-white">
            <X size={18} />
          </button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="text-[14px] text-[var(--mu)]">
            {t.name}
            <input ref={nameRef} className="field mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder={t.namePh} />
          </label>
          <label className="text-[14px] text-[var(--mu)]">
            {t.role}
            <input className="field mt-1" value={role} onChange={(e) => setRole(e.target.value)} placeholder={t.rolePh} />
          </label>
        </div>
        <div className="mt-4 text-[14px] text-[var(--mu)]">{t.kind}</div>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <button type="button" className="chip" data-on={parent === "hermes"} onClick={() => setParent("hermes")}>
            {"◉ "}
            {t.kindPlanet}
          </button>
          {parents.map((a) => (
            <button key={a.id} type="button" className="chip" data-on={parent === a.id} onClick={() => setParent(a.id)}>
              {t.kindMoon}
              {" "}
              {a.name}
            </button>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-6">
          <div>
            <div className="text-[14px] text-[var(--mu)]">{t.color}</div>
            <div className="mt-1.5 flex gap-2">
              {PALETTE.map((c, i) => (
                <button
                  key={i}
                  type="button"
                  aria-label={`color ${i + 1}`}
                  onClick={() => setColor(i)}
                  className="h-7 w-7 rounded-full transition"
                  style={{
                    background: `radial-gradient(circle, ${c} 0 30%, ${c}33 70%)`,
                    outline: color === i ? `2px solid ${c}` : "none",
                    outlineOffset: 2,
                  }}
                />
              ))}
            </div>
          </div>
          <div>
            <div className="text-[14px] text-[var(--mu)]">{t.initial}</div>
            <div className="mt-1.5 flex gap-2">
              {["running", "offline"].map((s) => (
                <button key={s} type="button" className="chip flex items-center gap-1.5" data-on={status === s} onClick={() => setStatus(s)}>
                  <i className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[s] }} />
                  {t.legend[s]}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button
            type="submit"
            disabled={!name.trim()}
            className="btn-core flex items-center justify-center gap-2 rounded-full py-3 font-semibold transition enabled:hover:brightness-110 disabled:opacity-40"
          >
            <Cable size={16} />
            {t.launch}
          </button>
          <button type="button" onClick={onCancel} className="rounded-full border border-[var(--line)] py-3 text-[var(--mu)] transition hover:text-white">
            {t.cancel}
          </button>
        </div>
      </form>
    </div>
  );
}
