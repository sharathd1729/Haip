export default function TermsPage() {
  return (
    <div className="bg-[#0D1B4B] text-white min-h-screen pt-24">
      <div className="max-w-3xl mx-auto px-5 sm:px-8 py-16">
        <p className="text-xs font-bold text-indigo-400 uppercase tracking-widest mb-4">Legal</p>
        <h1 className="text-4xl font-black tracking-tight mb-3">Terms of Service</h1>
        <p className="text-white/30 text-sm mb-10">Last updated: {new Date().toLocaleDateString("en-IN", { year: "numeric", month: "long", day: "numeric" })}</p>
        <div className="prose prose-invert max-w-none space-y-6 text-white/60 text-base leading-relaxed">
          <p>These Terms of Service govern your use of the HAIP platform operated by HAIP Technologies Pvt. Ltd. By using HAIP, you agree to these terms.</p>
          <h2 className="text-lg font-bold text-white">1. Service description</h2>
          <p>HAIP is a SaaS platform providing unified communication management, AI-powered call analysis, and CRM tools for the hospitality sector. The service is provided on a subscription basis.</p>
          <h2 className="text-lg font-bold text-white">2. Acceptable use</h2>
          <p>You may only use HAIP for lawful purposes. You must not use the platform to send spam, violate WhatsApp&apos;s policies, or process personal data without appropriate consent under applicable law.</p>
          <h2 className="text-lg font-bold text-white">3. Subscriptions and billing</h2>
          <p>Subscriptions are billed monthly or annually in advance. All prices are in Indian Rupees (INR) and include applicable GST. Refunds are provided at our discretion within 7 days of purchase.</p>
          <h2 className="text-lg font-bold text-white">4. Data and privacy</h2>
          <p>You retain ownership of your data. HAIP processes data as your data processor. See our Privacy Policy for full details.</p>
          <h2 className="text-lg font-bold text-white">5. Limitation of liability</h2>
          <p>HAIP&apos;s liability is limited to the amount you paid in the 3 months preceding the claim. We are not liable for indirect or consequential damages.</p>
          <h2 className="text-lg font-bold text-white">6. Governing law</h2>
          <p>These terms are governed by Indian law. Any disputes shall be subject to the exclusive jurisdiction of courts in Bengaluru, Karnataka.</p>
          <h2 className="text-lg font-bold text-white">7. Contact</h2>
          <p>For any questions, contact <a href="mailto:legal@haip.app" className="text-indigo-400">legal@haip.app</a>.</p>
        </div>
      </div>
    </div>
  );
}
