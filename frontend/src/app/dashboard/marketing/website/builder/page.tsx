import { redirect } from "next/navigation";

// The art director was retired from the screen (owner, Oct 2026: confusing, and its look didn't match the site). Old links
// land on the Website page, where Photos, Colours, Sections and Words edit the site directly.
export default function WebsiteBuilderPage() {
  redirect("/dashboard/marketing/website");
}
