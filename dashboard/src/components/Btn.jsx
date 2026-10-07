// Minified name in bundle: Vc.
export default function Btn({ icon: Icon, children, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-4 py-2 text-[14px] transition hover:border-[rgba(56,232,255,.5)] hover:text-[var(--sun2)]"
    >
      <Icon size={15} />
      {children}
    </button>
  );
}
