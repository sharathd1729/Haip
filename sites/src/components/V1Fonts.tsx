// A classic (v1) site's theme packs still use Google Fonts; v2 sites self-host theirs (lib/fonts.ts).
import { FONTS_HREF } from "@/site-blocks/packs";

export function V1Fonts() {
  return <link rel="stylesheet" href={FONTS_HREF} precedence="default" />;
}
