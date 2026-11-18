// Owner rule (18 Nov 2026): no AI-looking icons in the workspace or on the client websites: no sparkles, magic stars,
// wands, robots, chips or brains, and no such emoji. lib/icons.tsx keeps the names Sparkles/Wand2/Bot but draws neutral glyphs.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOTS = [resolve(process.cwd(), "src"), resolve(process.cwd(), "../sites/src")].filter(existsSync);
const AI_LUCIDE = /\b(Sparkles?|Stars|Wand2?|WandSparkles|Bot|BotMessageSquare|Brain|BrainCircuit|BrainCog|Cpu)\b/;
const AI_HERO = /\b(SparklesIcon|CpuChipIcon)\b/;
const AI_EMOJI = /[✨🤖🪄🧠]/u;

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) files(p, out);
    else if (/\.(tsx?|css)$/.test(name) && !name.endsWith("noAiIcons.test.ts")) out.push(p);
  }
  return out;
}

describe("no AI-looking icons", () => {
  it("nothing imports or shows one", () => {
    const bad: string[] = [];
    for (const f of ROOTS.flatMap(r => files(r))) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*["']lucide-react["']/g)) {
        if (AI_LUCIDE.test(m[1])) bad.push(`${f}: lucide ${m[1].match(AI_LUCIDE)![0]}`);
      }
      if (AI_HERO.test(src)) bad.push(`${f}: ${src.match(AI_HERO)![0]}`);
      if (AI_EMOJI.test(src)) bad.push(`${f}: emoji ${src.match(AI_EMOJI)![0]}`);
    }
    expect(bad).toEqual([]);
  });
});
