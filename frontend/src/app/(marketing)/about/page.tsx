import Link from "next/link";
import { ArrowRight } from "lucide-react";

export default function AboutPage() {
  return (
    <div className="bg-[#0D1B4B] text-white min-h-screen pt-24">
      <div className="max-w-3xl mx-auto px-5 sm:px-8 py-16">
        <p className="text-xs font-bold text-indigo-400 uppercase tracking-widest mb-4">About HAIP</p>
        <h1 className="text-4xl font-black tracking-tight mb-6">
          Built by hospitality people, for hospitality people
        </h1>
        <div className="prose prose-invert max-w-none space-y-6 text-white/60 text-base leading-relaxed">
          <p>
            HAIP (Hospitality AI Intelligence Platform) was born out of a frustration shared by every hospitality operator in India: too many tools, too many tabs, and too much time spent on admin instead of guests.
          </p>
          <p>
            We built HAIP to be the single intelligent layer between your team and your guests — combining unified communications, AI-powered call analysis, and a purpose-built CRM into one platform designed specifically for luxury hospitality operations.
          </p>
          <p>
            Today, HAIP is used by villa groups, boutique hotels, and travel operators across India to manage guest communications, analyze every call automatically, and recover revenue opportunities that would otherwise slip through the cracks.
          </p>
          <h2 className="text-xl font-bold text-white mt-8 mb-4">Our mission</h2>
          <p>
            To make every hospitality team look like they have a 24/7 AI concierge — without the complexity or cost of enterprise software.
          </p>
          <h2 className="text-xl font-bold text-white mt-8 mb-4">Made in India, for India</h2>
          <p>
            HAIP is built specifically for the Indian hospitality market — with support for Indian phone networks, WhatsApp as the primary communication channel, and DPDP-compliant data handling.
          </p>
        </div>
        <div className="mt-10">
          <Link href="/register" className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-500 hover:bg-indigo-400 text-white font-bold rounded-xl transition-all">
            Start free trial <ArrowRight size={16} />
          </Link>
        </div>
      </div>
    </div>
  );
}
