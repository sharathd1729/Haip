export default function OfflinePage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#0a1b30] px-6 text-center">
      <div className="w-16 h-16 rounded-2xl bg-teal-500/10 flex items-center justify-center mb-6">
        {/* Wifi-off icon */}
        <svg className="w-8 h-8 text-teal-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 3l18 18M8.111 8.111A7.5 7.5 0 0116.5 12m-4.5 4.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M6.343 6.343A8.25 8.25 0 0112 4.5c2.28 0 4.347.923 5.657 2.343M15 12a3 3 0 00-5.196-2.027" />
        </svg>
      </div>
      <h1 className="text-xl font-bold text-white mb-2">You&apos;re offline</h1>
      <p className="text-white/40 text-sm max-w-xs leading-relaxed">
        No internet connection. Check your network and try again.
      </p>
      <button
        onClick={() => window.location.reload()}
        className="mt-8 px-5 py-2.5 rounded-xl bg-teal-500 text-[#0a1b30] text-sm font-bold hover:bg-teal-400 transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
