/** Calculator segment layout — lets the calculator page use h-full. */
export default function CalculatorLayout({ children }: { children: React.ReactNode }) {
  return <div className="h-full overflow-hidden">{children}</div>;
}
