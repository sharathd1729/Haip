"use client";

/* Solutions page body (one design, content per property type), built from the approved mockup. */
import { useEffect, useRef, useState } from "react";
import { SOL_ICONS, type ChatLine, type Solution } from "./solutions";

function useInView<T extends Element>(threshold = 0.35) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(([e]) => setSeen(e.isIntersecting), { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

function useReducedMotion() {
  const [reduce, setReduce] = useState(false);
  useEffect(() => setReduce(window.matchMedia("(prefers-reduced-motion: reduce)").matches), []);
  return reduce;
}

const STATUS_BARS = ["35%", "55%", "75%", "95%"];

/** WhatsApp chat that plays message by message; the business types first. Restarts while the phone stays in view. */
function Chat({ biz, lines }: { biz: string; lines: ChatLine[] }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const reduce = useReducedMotion();
  const [count, setCount] = useState(0);
  const [typing, setTyping] = useState(false);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (reduce) {
      setCount(lines.length);
      return;
    }
    if (!seen) return;
    const timers: number[] = [];
    let t = 300;
    setCount(0);
    setTyping(false);
    lines.forEach((m, i) => {
      if (m[0] === "h") {
        timers.push(window.setTimeout(() => setTyping(true), t));
        t += 900;
      }
      timers.push(window.setTimeout(() => {
        setTyping(false);
        setCount(i + 1);
      }, t));
      t += m[0] === "g" ? 1200 : 1000;
    });
    timers.push(window.setTimeout(() => setRun((r) => r + 1), t + 3500));
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [seen, reduce, lines, run]);

  return (
    <div className="dev9" ref={ref}>
      <div className="ph9" aria-hidden="true">
        <div className="scrn">
          <div className="wa">
            <div className="sb9">
              9:41
              <span style={{ display: "inline-flex", alignItems: "center" }}>
                <i>
                  {STATUS_BARS.map((h) => (
                    <b key={h} style={{ height: h }} />
                  ))}
                </i>
                <em />
              </span>
            </div>
            <div className="wah">
              <i>{biz.charAt(0)}</i>
              <span>
                <b>{biz}</b>
                <span>Business account</span>
              </span>
            </div>
            <div className="wam">
              {lines.slice(0, count).map((m, i) =>
                m[0] === "s" ? (
                  <div key={i} className="wb s">{m[1]}</div>
                ) : (
                  <div key={i} className={`wb ${m[0]}`}>
                    {m[1]}
                    <small>
                      {m[2]}
                      {m[0] === "g" ? " ✓✓" : ""}
                    </small>
                  </div>
                ),
              )}
              {typing && (
                <div className="wb t">
                  <span>
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              )}
            </div>
            <div className="wai">
              <span>Message</span>
              <i />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** One big guest question at a time with HAIP's answer under it. */
function Questions({ qs }: { qs: [string, string][] }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const reduce = useReducedMotion();
  const [i, setI] = useState(0);
  const [out, setOut] = useState(false);

  useEffect(() => {
    if (reduce || !seen) return;
    const id = window.setTimeout(() => {
      setOut(true);
      window.setTimeout(() => {
        setI((n) => (n + 1) % qs.length);
        setOut(false);
      }, 360);
    }, 3400);
    return () => window.clearTimeout(id);
  }, [i, seen, reduce, qs.length]);

  return (
    <section className="sq gut" aria-labelledby="sqh">
      <div className="wrap" ref={ref}>
        <h2 className="k" id="sqh" style={{ margin: 0 }}>
          The questions you get every day
        </h2>
        <div className="qq">
          <span className={out ? "out" : ""}>{qs[i][0]}</span>
        </div>
        <div>
          <div className={`an${out ? " out" : ""}`}>
            <b>HAIP</b>
            <span>{qs[i][1]}</span>
          </div>
        </div>
        <div className="dots">
          {qs.map((q, k) => (
            <button key={q[0]} type="button" aria-label={`Question ${k + 1}`} className={k === i ? "on" : ""} onClick={() => setI(k)}>
              <i />
            </button>
          ))}
        </div>
        <p className="note">Answers come from your own details and rules. You set them once.</p>
      </div>
    </section>
  );
}

/** Five stops; one at a time, the line fills to it. */
function Timeline({ stops }: { stops: [string, string][] }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const reduce = useReducedMotion();
  const [si, setSi] = useState(0);

  useEffect(() => {
    if (reduce || !seen) return;
    const id = window.setTimeout(() => setSi((n) => (n + 1) % stops.length), 2600);
    return () => window.clearTimeout(id);
  }, [si, seen, reduce, stops.length]);

  return (
    <section className="st gut" aria-labelledby="sth">
      <div className="wrap">
        <h2 className="h2" id="sth">
          A stay, <em>start to finish.</em>
        </h2>
        <div className="tl" ref={ref} style={{ ["--f" as string]: si / (stops.length - 1) }}>
          <i className="fl" aria-hidden="true" />
          {stops.map((s, k) => (
            <button key={s[0]} type="button" className={`stop${k === si ? " on" : ""}${k < si ? " done" : ""}`} onClick={() => setSi(k)}>
              <span className="n">0{k + 1}</span>
              <span className="txt">
                <b>{s[0]}</b>
                <span>{s[1]}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function SolutionBody({ d }: { d: Solution }) {
  return (
    <>
      <section className="sh gut" aria-labelledby="sh1">
        <div className="wrap">
          <div className="g">
            <div>
              <span className="chip">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  {(SOL_ICONS[d.icon] || []).map((p) => (
                    <path key={p} fillRule="evenodd" clipRule="evenodd" d={p} />
                  ))}
                </svg>
                For {d.label.toLowerCase()}
              </span>
              <h1 id="sh1">
                {d.h1[0]}
                <em>{d.h1[1]}</em>
              </h1>
              <p className="l">{d.lead}</p>
              <div className="acts">
                <a className="btn big primary" href="/book-demo">Book a demo</a>
                <a className="btn big outline" href="https://wa.me/918147698153" target="_blank" rel="noopener noreferrer">Chat with us on WhatsApp</a>
              </div>
            </div>
            <Chat biz={d.biz} lines={d.chat} />
          </div>
        </div>
      </section>
      <Questions qs={d.qs} />
      <Timeline stops={d.stops} />
      <section className="sf gut" aria-labelledby="sfh">
        <div className="wrap">
          <h2 className="h2" id="sfh">
            Built for <em>{d.label.toLowerCase()}.</em>
          </h2>
          <ol>
            {d.feats.map((f, k) => (
              <li key={f[0]}>
                <span className="no">0{k + 1}</span>
                <b>{f[0]}</b>
                <span className="ds">{f[1]}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
