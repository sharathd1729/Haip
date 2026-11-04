// The website phase 3 Google checklist now lives in Get found (dynamic SOPs): its 12 items are the gbp_setup steps,
// tracked on the server instead of one browser (backend/app/services/sops/catalogue.py).
import { redirect } from "next/navigation";

export default function GoogleProfilePage() {
  redirect("/dashboard/marketing/sops");
}
