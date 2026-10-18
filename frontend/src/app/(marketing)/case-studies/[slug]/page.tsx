// /case-studies/{slug}: the owner-published snapshot of a workspace's impact numbers, or "coming soon" until there is one.
// Read on the server from the public API (cached 5 minutes); nothing here is placeholder copy.
import type { Metadata } from "next";
import { CaseStudyComingSoon, CaseStudyView } from "@/components/marketing/CaseStudyView";
import { fetchCaseStudy } from "@/lib/caseStudies";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const found = await fetchCaseStudy(slug);
  if (!found) return { title: "Case study coming soon | HAIP", robots: { index: false } };
  const s = found.snapshot;
  return { title: `${s.brand_name} case study | HAIP`, description: s.headline ?? `How ${s.brand_name} uses HAIP, in numbers the business approved.` };
}

export default async function CaseStudyPage({ params }: Props) {
  const { slug } = await params;
  const found = await fetchCaseStudy(slug);
  return found ? <CaseStudyView s={found.snapshot} /> : <CaseStudyComingSoon />;
}
