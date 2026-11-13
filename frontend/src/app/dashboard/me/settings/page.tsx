"use client";
// Yaad settings: custom words, notifications, delete my account.
import { YaadSettings } from "@/components/personal/YaadSettings";

export default function YaadSettingsPage() {
  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-[680px]">
        <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Settings</h1>
        <p className="mt-1 mb-5 text-[14.5px] text-[var(--y-ink-2)]">How Yaad writes your notes and tells you about them.</p>
        <YaadSettings />
      </div>
    </div>
  );
}
