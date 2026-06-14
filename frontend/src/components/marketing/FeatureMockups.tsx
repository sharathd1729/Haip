// Feature section mockup wireframes — marketing/features page

export function InboxMockup() {
  return (
    <div className="flex gap-2 h-64 text-[10px]">
      {/* Conversation list */}
      <div className="w-36 flex flex-col gap-1.5 flex-shrink-0">
        <p className="text-[9px] font-semibold uppercase tracking-widest mb-1" style={{ color: "#94A3B8" }}>Inbox</p>
        {[
          { ch: "WA", name: "Priya S.", msg: "Booking inquiry…", dot: "#25D366", active: true },
          { ch: "IG", name: "Rohit K.", msg: "Anniversary pkg…", dot: "#E1306C", active: false },
          { ch: "☎",  name: "+91 987…", msg: "Call · 4m 32s",   dot: "#00555a", active: false },
          { ch: "WA", name: "Suresh M.", msg: "Extend by 2…",   dot: "#25D366", active: false },
        ].map((c, i) => (
          <div
            key={i}
            className="flex items-center gap-1.5 p-1.5 rounded-lg"
            style={{ background: c.active ? "rgba(0,85,90,0.08)" : "transparent", borderLeft: c.active ? "2px solid #00555a" : "2px solid transparent" }}
          >
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-white font-bold text-[8px] flex-shrink-0" style={{ background: c.dot }}>{c.ch}</div>
            <div className="min-w-0">
              <p className="font-semibold truncate" style={{ color: "#0F172A" }}>{c.name}</p>
              <p className="truncate" style={{ color: "#94A3B8" }}>{c.msg}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Chat thread */}
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        <p className="font-semibold" style={{ color: "#0F172A" }}>Priya Sharma</p>
        <div className="rounded-xl p-2" style={{ background: "#F1F5F9" }}>
          <p style={{ color: "#334155" }}>Is the Sunset Villa available Dec 20–26?</p>
        </div>
        <div className="rounded-xl p-2 self-end max-w-[90%]" style={{ background: "rgba(0,85,90,0.10)" }}>
          <p style={{ color: "#00555a" }}>Hi Priya! Yes, available for 8 guests. Sending rates!</p>
        </div>
        {/* AI draft */}
        <div className="rounded-xl p-2 border" style={{ background: "rgba(255,201,75,0.08)", borderColor: "rgba(255,201,75,0.30)" }}>
          <p className="text-[8px] font-bold mb-1" style={{ color: "#00555a" }}>✦ AI Draft</p>
          <p style={{ color: "#334155" }}>Early check-in arranged for Dec 20 at 11 AM — no extra charge.</p>
        </div>
      </div>
    </div>
  );
}

export function CallsMockup() {
  const calls = [
    { name: "Priya Sharma", score: 91, dur: "8m 12s", col: "#00555a", bg: "rgba(0,85,90,0.08)", expanded: true },
    { name: "Rahul Verma",  score: 74, dur: "5m 44s", col: "#D97706", bg: "rgba(217,119,6,0.08)", expanded: false },
    { name: "Anjali P.",    score: 88, dur: "3m 20s", col: "#00555a", bg: "rgba(0,85,90,0.08)", expanded: false },
  ];
  return (
    <div className="space-y-2 text-[10px]">
      <p className="text-[9px] font-semibold uppercase tracking-widest mb-2" style={{ color: "#94A3B8" }}>Today's Calls</p>
      {calls.map((c, i) => (
        <div key={i}>
          <div className="flex items-center gap-2 p-2 rounded-lg" style={{ background: "#F8FAFC", border: "1px solid #E2E8F0" }}>
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-white font-bold text-[8px]" style={{ background: "#00555a" }}>{c.name[0]}</div>
            <span className="flex-1 font-semibold" style={{ color: "#0F172A" }}>{c.name}</span>
            <span className="text-[9px]" style={{ color: "#94A3B8" }}>{c.dur}</span>
            <span className="font-black px-1.5 py-0.5 rounded-full text-[8px]" style={{ background: c.bg, color: c.col }}>{c.score}</span>
          </div>
          {c.expanded && (
            <div className="mt-1 p-2 rounded-lg space-y-1" style={{ background: "#F8FAFC", border: "1px solid #E2E8F0" }}>
              <p style={{ color: "#64748B" }}><b style={{ color: "#00555a" }}>AGENT:</b> Good morning, how may I help?</p>
              <p style={{ color: "#64748B" }}><b>GUEST:</b> I'd like the pool villa for New Year's week.</p>
              <div className="flex items-start gap-1.5 rounded-lg p-1.5 mt-1" style={{ background: "rgba(255,201,75,0.12)", border: "1px solid rgba(255,201,75,0.35)" }}>
                <span style={{ color: "#ffc94b" }}>⚠</span>
                <span style={{ color: "#334155" }}>Missed upsell: Private chef not offered (₹8,000)</span>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function CRMMockup() {
  const cols = [
    { label: "New",      color: "#3B82F6", leads: [{ name: "Priya S.", val: "₹84k" }, { name: "Vikram R.", val: "₹60k" }] },
    { label: "Quoted",   color: "#00555a", leads: [{ name: "Anjali M.", val: "₹1.2L" }] },
    { label: "Booked",   color: "#10B981", leads: [{ name: "Suresh K.", val: "₹42k" }, { name: "Nita P.", val: "₹96k" }] },
  ];
  return (
    <div className="flex gap-2 text-[10px] h-52">
      {cols.map(col => (
        <div key={col.label} className="flex-1 flex flex-col gap-1.5" style={{ minWidth: 0 }}>
          <div className="flex items-center gap-1 mb-0.5">
            <span className="font-semibold" style={{ color: "#0F172A" }}>{col.label}</span>
            <span className="rounded-full px-1.5 text-[8px] font-bold" style={{ background: `${col.color}15`, color: col.color }}>{col.leads.length}</span>
          </div>
          {col.leads.map((l, i) => (
            <div key={i} className="rounded-lg p-2" style={{ background: "#ffffff", border: "1px solid #E2E8F0" }}>
              <p className="font-semibold truncate" style={{ color: "#0F172A" }}>{l.name}</p>
              <span className="rounded-full px-1.5 py-0.5 font-bold text-[8px]" style={{ background: `${col.color}15`, color: col.color }}>{l.val}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function WhatsAppMockup() {
  return (
    <div className="space-y-3 text-[10px]">
      <p className="text-[9px] font-semibold uppercase tracking-widest mb-2" style={{ color: "#94A3B8" }}>Campaign Builder</p>
      <div className="rounded-xl p-3" style={{ background: "#F8FAFC", border: "1px solid #E2E8F0" }}>
        <p className="font-semibold mb-1" style={{ color: "#0F172A" }}>New Year Availability — 2024</p>
        <div className="rounded-lg p-2 mb-2" style={{ background: "#ffffff", border: "1px solid #E2E8F0" }}>
          <p style={{ color: "#334155" }}>Hi {'{{name}}'}, Sunset Villa has limited availability for New Year's. Book by Dec 20 for early-bird rates! 🎉</p>
        </div>
        <div className="grid grid-cols-4 gap-1 text-center">
          {[{ l: "Sent", v: "847" }, { l: "Delivered", v: "831" }, { l: "Read", v: "612" }, { l: "Replied", v: "134" }].map(s => (
            <div key={s.l} className="rounded-lg p-1.5" style={{ background: "#ffffff", border: "1px solid #E2E8F0" }}>
              <p className="font-black" style={{ color: "#00555a" }}>{s.v}</p>
              <p style={{ color: "#94A3B8" }}>{s.l}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function QAMockup() {
  return (
    <div className="space-y-3 text-[10px]">
      <p className="text-[9px] font-semibold uppercase tracking-widest mb-2" style={{ color: "#94A3B8" }}>Auto QA Dashboard</p>
      {/* Coverage meter */}
      <div className="flex items-center gap-3 p-3 rounded-xl" style={{ background: "#F8FAFC", border: "1px solid #E2E8F0" }}>
        <div className="relative w-14 h-14 flex-shrink-0">
          <svg viewBox="0 0 36 36" className="w-14 h-14 -rotate-90">
            <circle cx="18" cy="18" r="15" fill="none" stroke="#E2E8F0" strokeWidth="3" />
            <circle cx="18" cy="18" r="15" fill="none" stroke="#00555a" strokeWidth="3" strokeDasharray="94 6" strokeLinecap="round" />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center font-black" style={{ color: "#00555a", fontSize: 10 }}>100%</span>
        </div>
        <div>
          <p className="font-semibold" style={{ color: "#0F172A" }}>Call Coverage</p>
          <p style={{ color: "#64748B" }}>Every call automatically scored</p>
        </div>
      </div>
      {/* Agent scores */}
      {[{ name: "Ravi Kumar", score: 91 }, { name: "Priya Sharma", score: 78 }, { name: "Ankit V.", score: 65 }].map(a => (
        <div key={a.name} className="flex items-center gap-2 p-2 rounded-lg" style={{ background: "#F8FAFC", border: "1px solid #E2E8F0" }}>
          <div className="w-5 h-5 rounded-full font-bold text-[8px] flex items-center justify-center text-white flex-shrink-0" style={{ background: "#00555a" }}>{a.name[0]}</div>
          <span className="flex-1 font-medium" style={{ color: "#0F172A" }}>{a.name}</span>
          <span className="font-black text-[9px]" style={{ color: a.score >= 80 ? "#00555a" : a.score >= 70 ? "#D97706" : "#DC2626" }}>{a.score}</span>
        </div>
      ))}
    </div>
  );
}

export function InsightsMockup() {
  return (
    <div className="space-y-2.5 text-[10px]">
      <p className="text-[9px] font-semibold uppercase tracking-widest mb-2" style={{ color: "#94A3B8" }}>AI Insights — This Week</p>
      {[
        { icon: "💡", title: "Top missed upsell", body: "Private chef not offered in 34% of bookings — ₹2.8L potential", type: "mimosa" },
        { icon: "📈", title: "Peak inquiry time", body: "Friday 6–8 PM sees 3× more WhatsApp inquiries than average", type: "teal" },
        { icon: "🏆", title: "Best performing agent", body: "Rahul Kumar — 94 avg QA score, highest conversion rate this month", type: "teal" },
      ].map((ins, i) => (
        <div
          key={i}
          className="flex items-start gap-2 p-3 rounded-xl"
          style={ins.type === "mimosa"
            ? { background: "rgba(255,201,75,0.08)", border: "1px solid rgba(255,201,75,0.25)" }
            : { background: "rgba(0,85,90,0.06)", border: "1px solid rgba(0,85,90,0.15)" }
          }
        >
          <span className="text-sm flex-shrink-0">{ins.icon}</span>
          <div>
            <p className="font-semibold mb-0.5" style={{ color: ins.type === "mimosa" ? "#92400E" : "#00555a" }}>{ins.title}</p>
            <p style={{ color: "#475569" }}>{ins.body}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
