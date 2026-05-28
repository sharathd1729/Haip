/** Portfolio segment layout — lets sub-pages use h-full for fixed-height layouts. */
export default function PortfolioLayout({ children }: { children: React.ReactNode }) {
  return <div className="h-full overflow-hidden">{children}</div>;
}
