export default function PrivacyPage() {
  return (
    <div className="bg-[#0E1210] text-white min-h-screen pt-24">
      <div className="max-w-3xl mx-auto px-5 sm:px-8 py-16">
        <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-4">Legal</p>
        <h1 className="text-4xl font-black tracking-tight mb-3">Privacy Policy</h1>
        <p className="text-white/30 text-sm mb-10">Last updated: {new Date().toLocaleDateString("en-IN", { year: "numeric", month: "long", day: "numeric" })}</p>
        <div className="prose prose-invert max-w-none space-y-6 text-white/60 text-base leading-relaxed">
          <p>HAIP Technologies Pvt. Ltd. (&quot;HAIP&quot;, &quot;we&quot;, &quot;our&quot;) operates the HAIP platform. This Privacy Policy describes how we collect, use, and protect your information.</p>
          <h2 className="text-lg font-bold text-white">1. Information we collect</h2>
          <p>We collect information you provide directly (name, email, phone, business details), usage data (platform interactions, call metadata), and data from connected integrations (WhatsApp messages, call recordings) as authorized by you.</p>
          <h2 className="text-lg font-bold text-white">2. How we use your information</h2>
          <p>To provide and improve the HAIP service, process transactions, send service communications, and comply with legal obligations under the Digital Personal Data Protection Act, 2023 (DPDP).</p>
          <h2 className="text-lg font-bold text-white">3. Data storage and security</h2>
          <p>All data is stored in India on AWS infrastructure. Credentials are encrypted at rest using AES-256. Call recordings are retained per your plan&apos;s retention policy and can be deleted on request.</p>
          <h2 className="text-lg font-bold text-white">4. DPDP Compliance</h2>
          <p>HAIP is designed to comply with the Digital Personal Data Protection Act, 2023. We act as a Data Fiduciary and Data Processor as applicable. We support data subject rights including access, correction, and erasure.</p>
          <h2 className="text-lg font-bold text-white">5. Contact</h2>
          <p>For privacy enquiries, contact us at <a href="mailto:privacy@haip.app" className="text-teal-400">privacy@haip.app</a>.</p>
        </div>
      </div>
    </div>
  );
}
