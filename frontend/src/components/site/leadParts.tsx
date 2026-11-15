// Small pieces shared by the Book a demo and Contact pages (no hooks, so server and client components can both use them).
import type { ReactNode } from "react";

export const WA_NUMBER = "+918147698153";

export function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="lff">
      <span>
        {label}
        {required && <b aria-hidden="true"> *</b>}
      </span>
      {children}
    </label>
  );
}

export function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd" d="M12.97 3.97a.75.75 0 0 1 1.06 0l7.5 7.5a.75.75 0 0 1 0 1.06l-7.5 7.5a.75.75 0 1 1-1.06-1.06l6.22-6.22H3a.75.75 0 0 1 0-1.5h16.19l-6.22-6.22a.75.75 0 0 1 0-1.06Z" />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd" d="M19.916 4.626a.75.75 0 0 1 .208 1.04l-9 13.5a.75.75 0 0 1-1.154.114l-6-6a.75.75 0 0 1 1.06-1.06l5.353 5.353 8.493-12.74a.75.75 0 0 1 1.04-.207Z" />
    </svg>
  );
}

export function WhatsAppIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd" d="M4.804 21.644A6.707 6.707 0 0 0 6 21.75a6.721 6.721 0 0 0 3.583-1.029c.774.182 1.584.279 2.417.279 5.322 0 9.75-3.97 9.75-9 0-5.03-4.428-9-9.75-9s-9.75 3.97-9.75 9c0 2.409 1.025 4.587 2.674 6.192.232.226.277.428.254.543a3.73 3.73 0 0 1-.814 1.686.75.75 0 0 0 .44 1.223ZM8.25 10.875a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25ZM10.875 12a1.125 1.125 0 1 1 2.25 0 1.125 1.125 0 0 1-2.25 0Zm4.875-1.125a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25Z" />
    </svg>
  );
}

export function WhatsAppLine({ lead = "Rather talk now?" }: { lead?: string }) {
  return (
    <p className="lpa">
      {lead}
      <a href={`https://wa.me/${WA_NUMBER}`} target="_blank" rel="noopener noreferrer">
        <WhatsAppIcon /> WhatsApp +91 81476 98153
      </a>
    </p>
  );
}

/** Faint outline arch behind the page (the site's Indian touch: thin lines, ~10% opacity, no motion). */
export function ArchMark() {
  return (
    <svg className="lpm" viewBox="0 0 400 420" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M40 420V200C40 110 112 40 200 40s160 70 160 160v220" />
      <path d="M80 420V210c0-68 54-124 120-124s120 56 120 124v210" />
      <path d="M120 420V222c0-46 36-84 80-84s80 38 80 84v198" />
      <path d="M200 40v-24M188 16h24" />
      <circle cx="200" cy="230" r="14" />
    </svg>
  );
}
