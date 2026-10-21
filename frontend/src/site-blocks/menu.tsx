"use client";
import { Menu, X } from "lucide-react";
import { useState } from "react";

export function MobileMenu({ links }: { links: { href: string; title: string }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="k-btn ghost k-menu" style={{ minHeight: 40, padding: "0 12px" }} aria-expanded={open}
        aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(o => !o)}>
        {open ? <X size={18} aria-hidden="true" /> : <Menu size={18} aria-hidden="true" />}
      </button>
      {open && (
        <nav className="k-mlinks" aria-label="Menu" style={{ position: "absolute", top: "100%", left: 0, right: 0, background: "var(--k-bg)", borderBottom: "1px solid var(--k-line)" }}>
          {links.map(l => <a key={l.href} href={l.href} onClick={() => setOpen(false)}>{l.title}</a>)}
        </nav>
      )}
    </>
  );
}
