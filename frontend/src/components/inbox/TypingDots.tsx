"use client";
import { cn } from "@/lib/utils";

export function TypingDots({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-1 px-3 py-2 bg-gray-100 rounded-2xl rounded-bl-sm w-fit", className)}>
      {[0, 1, 2].map(i => (
        <div
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s`, animationDuration: "0.8s" }}
        />
      ))}
    </div>
  );
}
