"use client";
// Video hero (website phase 5): the poster photo is server-rendered; the video is added after load ONLY when the visitor
// hasn't asked for reduced motion, so they never download it. Always muted, inline, looping, no sound track (HAIP strips
// audio on upload), no controls, decorative (aria-hidden): the headline carries the meaning.
import { useEffect, useState } from "react";

export function HeroVideo({ src, poster }: { src: string; poster?: string }) {
  const [play, setPlay] = useState(false);
  useEffect(() => {
    const m = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    setPlay(!m?.matches);
  }, []);
  if (!play) return null;
  return <video className="sv-hero__video" src={src} poster={poster} autoPlay muted loop playsInline preload="metadata" aria-hidden="true" />;
}
