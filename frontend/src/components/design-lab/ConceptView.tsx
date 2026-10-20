"use client";
// Picks the concept and keeps its current screen. Navigation inside a concept switches screens locally, so a preview frame
// behaves like the real app; the lab changes the starting screen by changing the frame's URL.
import { useEffect, useState } from "react";
import type { ConceptId, Screen } from "./concepts";
import Atlas from "./concepts/atlas";
import Milestone from "./concepts/milestone";
import Atelier from "./concepts/atelier";
import Calm from "./concepts/calm";
import Command from "./concepts/command";
import Hybrid from "./concepts/hybrid";

const VIEWS = { atlas: Atlas, milestone: Milestone, atelier: Atelier, calm: Calm, command: Command, hybrid: Hybrid } as const;

export function ConceptView({ concept, initialScreen }: { concept: ConceptId; initialScreen: Screen }) {
  const [screen, setScreen] = useState<Screen>(initialScreen);
  useEffect(() => setScreen(initialScreen), [initialScreen]);
  const View = VIEWS[concept];
  return <View screen={screen} go={setScreen} />;
}
