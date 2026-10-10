// Workspace operations: export, import (with a validation
// preview BEFORE applying), and per-section reset.
//
// Only non-secret workspace configuration is handled here.
// Browser storage is LOCAL — not multi-user persistence.
import { useEffect, useRef, useState } from "react";
import { Download, RotateCcw, Upload } from "lucide-react";
import { parseImport } from "../adapter/storage.js";

export default function WorkspaceTools({
  t,
  onExport,
  onImport,
  onReset,
  parseContext,
}) {
  const fileRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  // reset section awaiting a second confirming click
  const [confirming, setConfirming] = useState(null);
  // import preview: { workspace, errors } | { fatal: errors[] }
  const [preview, setPreview] = useState(null);

  // the two-click confirm expires
  useEffect(() => {
    if (!confirming) return;
    const iv = setTimeout(() => setConfirming(null), 3000);
    return () => clearTimeout(iv);
  }, [confirming]);

  // close popovers with Escape
  useEffect(() => {
    if (!menuOpen && !preview) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setPreview(null);
        setConfirming(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen, preview]);

  const onFile = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = ""; // allow re-importing the same file
    if (!file) return;
    setMenuOpen(false);
    const text = await file.text();
    const parsed = parseImport(text, parseContext);
    setPreview(
      parsed.ok
        ? { workspace: parsed.workspace, errors: parsed.errors }
        : { fatal: parsed.errors }
    );
  };

  // Layout resets immediately; destructive sections ask for
  // a second confirming click.
  const requestReset = (section) => {
    if (section === "layout" || confirming === section) {
      setConfirming(null);
      setMenuOpen(false);
      onReset(section);
      return;
    }
    setConfirming(section);
  };

  const counts =
    preview && preview.workspace
      ? [
          [t.importTools, preview.workspace.customTools.length],
          [
            t.importConnections,
            preview.workspace.connections ? preview.workspace.connections.length : "—",
          ],
          [t.importView, preview.workspace.view ? 1 : 0],
          [
            t.importNav,
            preview.workspace.manifest ? preview.workspace.manifest.items.length : "—",
          ],
          [t.importPages, preview.workspace.pages ? preview.workspace.pages.length : "—"],
        ]
      : [];

  return (
    <div className="relative flex items-center gap-2">
      <button
        type="button"
        onClick={onExport}
        className="chip"
        title={t.storageNote}
      >
        <Download size={13} />
        {t.export}
      </button>

      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        className="chip"
      >
        <Upload size={13} />
        {t.import}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={onFile}
        aria-label={t.import}
      />

      <div className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          className="chip"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
        >
          <RotateCcw size={13} />
          {t.resetMenu}
        </button>
        {menuOpen && (
          <div
            className="glass rise absolute end-0 top-full z-40 mt-2 w-[270px] p-2"
            role="menu"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => requestReset("layout")}
              className="chip w-full justify-start"
            >
              {t.resetLayout}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => requestReset("workspace")}
              className="chip w-full justify-start"
              data-on={confirming === "workspace"}
            >
              {confirming === "workspace" ? t.confirm : t.resetWorkspace}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => requestReset("all")}
              className="chip w-full justify-start"
              data-on={confirming === "all"}
            >
              {confirming === "all" ? t.confirm : t.resetAll}
            </button>
            <div className="px-2 pb-1 pt-2 text-[11px] text-[var(--mu)]">
              {t.storageNote}
            </div>
          </div>
        )}
      </div>

      {preview && (
        <div
          className="glass rise absolute end-0 top-full z-40 mt-2 w-[330px] p-4"
          role="dialog"
          aria-label={t.importPreview}
        >
          <div className="disp text-[16px]">{t.importPreview}</div>
          {preview.fatal ? (
            <>
              <div className="mt-2 text-[14px] text-[#ff5c7a]">{t.importFatal}</div>
              <ul className="mt-2 flex flex-col gap-1 text-[13px] text-[var(--mu)]">
                {preview.fatal.map((e, i) => (
                  <li key={`f-${i}`}>• {e}</li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <ul className="mt-2 flex flex-col gap-1 text-[14px]">
                {counts.map(([label, n]) => (
                  <li key={label} className="flex items-center gap-2">
                    <span className="mono min-w-[2ch] text-[12px] text-[var(--sun2)]">{n}</span>
                    {label}
                  </li>
                ))}
              </ul>
              {preview.errors.length > 0 && (
                <ul className="mt-2 flex max-h-[120px] flex-col gap-1 overflow-auto text-[12px] text-[#ffd166]">
                  {preview.errors.map((e, i) => (
                    <li key={`e-${i}`}>• {e}</li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11px] text-[var(--mu)]">{t.storageNote}</p>
            </>
          )}
          <div className="mt-3 flex gap-2">
            {!preview.fatal && (
              <button
                type="button"
                onClick={() => {
                  const workspace = preview.workspace;
                  setPreview(null);
                  onImport(workspace);
                }}
                className="btn-core flex-1 rounded-full px-3 py-2 text-[13px] font-semibold"
              >
                {t.importApply}
              </button>
            )}
            <button
              type="button"
              onClick={() => setPreview(null)}
              className="chip flex-1 justify-center"
            >
              {t.cancel}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
