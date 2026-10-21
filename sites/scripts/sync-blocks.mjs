// Copies the shared site sections from the HAIP frontend (the editor uses the same files) into src/site-blocks.
// The copy is generated (git-ignored). In the Docker build the frontend folder is copied in first, so the source
// always exists; when it doesn't (an image built from an older context) the existing copy is kept.
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "frontend", "src", "site-blocks");
const dest = join(here, "..", "src", "site-blocks");
if (!existsSync(src)) {
  if (!existsSync(dest)) { console.error("site-blocks source missing:", src); process.exit(1); }
  console.log("site-blocks: source missing, keeping existing copy");
} else {
  rmSync(dest, { recursive: true, force: true });
  cpSync(src, dest, { recursive: true, filter: f => !/\.test\.tsx?$/.test(f) });
  console.log("site-blocks: synced from frontend");
}
