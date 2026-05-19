"use client";
import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { X, Keyboard } from "lucide-react";

const SHORTCUTS = [
  { group: "Composer",
    items: [
      { keys: ["⌘", "Enter"],  desc: "Send message" },
      { keys: ["Shift", "↵"],  desc: "New line" },
      { keys: ["/"],           desc: "Open saved replies" },
    ]
  },
  { group: "Navigation",
    items: [
      { keys: ["j"],  desc: "Next item in list" },
      { keys: ["k"],  desc: "Previous item in list" },
      { keys: ["e"],  desc: "Archive conversation" },
      { keys: ["r"],  desc: "Reply (focus composer)" },
    ]
  },
  { group: "Global",
    items: [
      { keys: ["/"],    desc: "Focus search" },
      { keys: ["?"],    desc: "Show this overlay" },
      { keys: ["Esc"],  desc: "Close modal / overlay" },
    ]
  },
];

interface ShortcutsOverlayProps {
  onClose: () => void;
}

export function ShortcutsOverlay({ onClose }: ShortcutsOverlayProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200] p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-100">
          <div className="w-8 h-8 rounded-xl bg-gray-100 flex items-center justify-center">
            <Keyboard size={16} className="text-gray-600" />
          </div>
          <h2 className="font-bold text-gray-900 flex-1">Keyboard shortcuts</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
          {SHORTCUTS.map(group => (
            <div key={group.group}>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-3">{group.group}</p>
              <div className="space-y-2">
                {group.items.map(item => (
                  <div key={item.desc} className="flex items-center justify-between">
                    <span className="text-sm text-gray-700">{item.desc}</span>
                    <div className="flex items-center gap-1">
                      {item.keys.map(k => (
                        <kbd
                          key={k}
                          className="px-1.5 py-0.5 text-xs font-mono text-gray-600 bg-gray-100 border border-gray-200 rounded-md"
                        >
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="px-6 py-3 border-t border-gray-100 bg-gray-50">
          <p className="text-[11px] text-gray-400 text-center">Shortcuts disabled while typing in a text field</p>
        </div>
      </div>
    </div>
  );
}
