"use client";

import { useMemo, useRef, useState } from "react";
import type { ComponentType, CSSProperties } from "react";
import {
  motion, useMotionValue, useSpring, useTransform, useReducedMotion,
} from "framer-motion";
import { MessageCircle, Camera, Phone, Home, Building2, Search, Building, Wallet, CreditCard, Sparkles } from "@/lib/icons";
import { viewportOnce } from "../shared/motion";

type IconComponent = ComponentType<{ size?: number; className?: string; style?: CSSProperties }>;
type Node = { id: string; label: string; icon: IconComponent };

// Curated set for the visual ring. OpenAI / Claude / Sarvam AI are
// intentionally merged into one "AI Engine" node rather than shown as raw
// provider marks — the LLM router picks a model per task, so no single
// provider is a stable, guest-facing "integration".
const NODES: Node[] = [
  { id: "whatsapp", label: "WhatsApp", icon: MessageCircle },
  { id: "instagram", label: "Instagram", icon: Camera },
  { id: "voice", label: "Voice AI", icon: Phone },
  { id: "airbnb", label: "Airbnb", icon: Home },
  { id: "booking", label: "Booking.com", icon: Building2 },
  { id: "google", label: "Google", icon: Search },
  { id: "rentalwise", label: "RentalWise", icon: Building },
  { id: "razorpay", label: "Razorpay", icon: Wallet },
  { id: "stripe", label: "Stripe", icon: CreditCard },
  { id: "ai", label: "AI Engine", icon: Sparkles },
];

const RADIUS_PCT = 40;

function polar(index: number, total: number) {
  const angle = (index / total) * Math.PI * 2 - Math.PI / 2;
  return {
    x: 50 + RADIUS_PCT * Math.cos(angle),
    y: 50 + RADIUS_PCT * Math.sin(angle),
  };
}

/**
 * Circular integration diagram: HAIP at the center, channels/tools orbiting
 * around it, connected by animated SVG lines with a traveling data dot.
 * Desktop-only — mobile renders the simpler stacked grid in the section.
 */
export function IntegrationOrbit() {
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [hoveredCenter, setHoveredCenter] = useState(false);

  const positions = useMemo(
    () => NODES.map((n, i) => ({ ...n, ...polar(i, NODES.length) })),
    []
  );

  // Container-level tilt driven by cursor position — a light, premium
  // parallax rather than per-card cursor-distance physics.
  const mvX = useMotionValue(0);
  const mvY = useMotionValue(0);
  const rotateX = useSpring(useTransform(mvY, [-0.5, 0.5], [4, -4]), { stiffness: 120, damping: 16 });
  const rotateY = useSpring(useTransform(mvX, [-0.5, 0.5], [-4, 4]), { stiffness: 120, damping: 16 });

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (reduced || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    mvX.set((e.clientX - rect.left) / rect.width - 0.5);
    mvY.set((e.clientY - rect.top) / rect.height - 0.5);
  }
  function handleMouseLeave() {
    mvX.set(0);
    mvY.set(0);
    setHovered(null);
  }

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className="relative mx-auto aspect-square w-full max-w-[600px]"
      style={{ perspective: 1000 }}
    >
      {/* Subtle grid + radial glow backdrop */}
      <div
        className="absolute inset-0 rounded-full pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(circle, rgba(11,107,94,0.10) 0%, rgba(11,107,94,0) 65%)," +
            "linear-gradient(rgba(17,17,17,0.05) 1px, transparent 1px)," +
            "linear-gradient(90deg, rgba(17,17,17,0.05) 1px, transparent 1px)",
          backgroundSize: "auto, 28px 28px, 28px 28px",
        }}
      />

      <motion.div
        className="absolute inset-0"
        style={reduced ? undefined : { rotateX, rotateY, transformStyle: "preserve-3d" }}
      >
        {/* Connection lines */}
        <svg
          className="absolute inset-0 w-full h-full overflow-visible"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {positions.map((n, i) => {
            const active = hovered === n.id || hoveredCenter;
            return (
              <motion.line
                key={n.id}
                x1={n.x}
                y1={n.y}
                x2={50}
                y2={50}
                stroke={active ? "var(--home-accent)" : "var(--home-border)"}
                strokeWidth={active ? 0.5 : 0.3}
                vectorEffect="non-scaling-stroke"
                initial={reduced ? undefined : { pathLength: 0, opacity: 0 }}
                whileInView={reduced ? undefined : { pathLength: 1, opacity: 1 }}
                viewport={viewportOnce}
                transition={{ duration: 0.7, delay: 0.15 + i * 0.05, ease: "easeOut" }}
                animate={{ stroke: active ? "var(--home-accent)" : "var(--home-border)" }}
              />
            );
          })}
        </svg>

        {/* Traveling data dots — subtle, staggered, looping */}
        {!reduced && (
          <svg className="absolute inset-0 w-full h-full overflow-visible" viewBox="0 0 100 100" aria-hidden="true">
            {positions.map((n, i) => (
              <motion.circle
                key={`dot-${n.id}`}
                r={0.7}
                fill="var(--home-accent)"
                initial={{ cx: n.x, cy: n.y, opacity: 0 }}
                animate={{
                  cx: [n.x, 50],
                  cy: [n.y, 50],
                  opacity: [0, 1, 0],
                }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                  repeatDelay: NODES.length * 0.4,
                  delay: 1.5 + i * 0.4,
                  ease: "easeInOut",
                }}
              />
            ))}
          </svg>
        )}

        {/* Center HAIP node */}
        <motion.div
          className="absolute w-20 h-20 sm:w-24 sm:h-24 rounded-2xl flex flex-col items-center justify-center gap-0.5 cursor-default"
          style={{
            left: "50%",
            top: "50%",
            translateX: "-50%",
            translateY: "-50%",
            backgroundColor: "var(--home-accent)",
            boxShadow: "var(--home-shadow-lg)",
          }}
          initial={reduced ? undefined : { opacity: 0, scale: 0.8 }}
          whileInView={reduced ? undefined : { opacity: 1, scale: 1 }}
          viewport={viewportOnce}
          transition={{ duration: 0.5, ease: "easeOut" }}
          onMouseEnter={() => setHoveredCenter(true)}
          onMouseLeave={() => setHoveredCenter(false)}
        >
          <span className="text-white font-bold text-sm sm:text-base tracking-tight">HAIP</span>
          <span className="text-white/70 text-[9px] font-medium">Core</span>
        </motion.div>

        {/* Orbiting integration nodes */}
        {positions.map((n, i) => {
          const Icon = n.icon;
          const isHovered = hovered === n.id;
          return (
            <motion.div
              key={n.id}
              className="absolute flex flex-col items-center gap-1.5"
              style={{ left: `${n.x}%`, top: `${n.y}%`, translateX: "-50%", translateY: "-50%" }}
              initial={reduced ? undefined : { opacity: 0, scale: 0.85 }}
              whileInView={reduced ? undefined : { opacity: 1, scale: 1 }}
              viewport={viewportOnce}
              transition={{ duration: 0.4, delay: 0.3 + i * 0.06, ease: "easeOut" }}
              animate={reduced ? undefined : { y: isHovered ? -6 : 0 }}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => setHovered(null)}
            >
              <motion.div
                className="w-14 h-14 sm:w-16 sm:h-16 rounded-2xl flex items-center justify-center border"
                style={{
                  backgroundColor: "var(--home-card)",
                  borderColor: isHovered ? "rgba(11,107,94,0.35)" : "var(--home-border)",
                  boxShadow: isHovered ? "var(--home-shadow-md)" : "var(--home-shadow-sm)",
                }}
                animate={reduced ? undefined : { scale: isHovered ? 1.08 : 1 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                <Icon size={20} style={{ color: "var(--home-accent)" }} />
              </motion.div>
              <span
                className="hidden sm:block text-[10px] font-medium whitespace-nowrap px-1.5 py-0.5 rounded-full"
                style={{
                  color: isHovered ? "var(--home-accent)" : "var(--home-text-subtle)",
                  backgroundColor: isHovered ? "var(--home-accent-soft)" : "transparent",
                }}
              >
                {n.label}
              </span>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}
