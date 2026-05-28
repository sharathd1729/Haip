/**
 * Inbox segment layout — overrides the default scroll wrapper so the
 * 3-column inbox can manage its own independent scroll areas.
 *
 * The parent dashboard layout has:
 *   <main overflow-hidden flex-col>
 *     <div flex-1 overflow-y-auto pb-20>   ← default page scroller
 *       {children}                          ← this layout renders here
 *     </div>
 *   </main>
 *
 * The inbox page root uses `h-full overflow-hidden` to create a fixed-height
 * 3-column layout. We wrap it in another h-full container so the percentage
 * resolves against the scroller div's defined height.
 */
export default function InboxLayout({ children }: { children: React.ReactNode }) {
  return (
    // h-full resolves against flex-1 scroller's defined height
    // overflow-hidden prevents the inbox from leaking into the bottom pb-20 area
    <div className="h-full overflow-hidden">
      {children}
    </div>
  );
}
