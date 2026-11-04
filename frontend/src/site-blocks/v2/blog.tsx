// Guides (website phase 5): /blog lists approved guides, /blog/<slug> shows one. Server-rendered; data from the guest API
// (backend website_blog: approved versions only). Body: blank line = new paragraph, "## " = a sub-heading.
import type { SiteEnv } from "../types";
import { hrefOf } from "../types";

export interface BlogItem { slug: string; title: string; excerpt: string; media: string | null; date: string | null }
export interface Article extends BlogItem { body: string; seo_description: string }

const day = (d: string | null) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" }) : "");
const photo = (env: SiteEnv, id: string | null, w: number) => (id && env.mode === "live" ? `/_haip/media/${id}?w=${w}` : null);

export function BlogList({ items, env }: { items: BlogItem[]; env: SiteEnv }) {
  return (
    <section className="sv-sec sv-blog">
      <div className="sv-wrap">
        <header className="sv-head"><p className="sv-eyebrow">Guides</p><h1 className="sv-h2">Plan your trip</h1></header>
        {!items.length ? <p className="sv-lede">New guides are on their way.</p> : (
          <ul className="sv-blog__grid">{items.map(i => {
            const src = photo(env, i.media, 640);
            return (
              <li key={i.slug} className="sv-blog__card">
                <a href={hrefOf(env, `/blog/${i.slug}`)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {src && <img src={src} alt="" loading="lazy" decoding="async" width={640} height={400} />}
                  <h2 className="sv-h3">{i.title}</h2>
                  <p className="sv-muted">{i.excerpt}</p>
                  {i.date && <p className="sv-meta">{day(i.date)}</p>}
                </a>
              </li>
            );
          })}</ul>
        )}
      </div>
    </section>
  );
}

export function ArticleView({ a, env }: { a: Article; env: SiteEnv }) {
  const blocks = a.body.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean);
  const src = photo(env, a.media, 1280);
  return (
    <article className="sv-sec sv-article">
      <div className="sv-wrap sv-narrow">
        <p className="sv-meta"><a href={hrefOf(env, "/blog")}>Guides</a>{a.date ? ` · ${day(a.date)}` : ""}</p>
        <h1 className="sv-h2">{a.title}</h1>
        <p className="sv-lede">{a.excerpt}</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {src && <img className="sv-article__photo" src={src} alt="" decoding="async" width={1280} height={800} />}
        <div className="sv-own">{blocks.map((b, i) => (b.startsWith("## ")
          ? <h2 key={i} className="sv-h3">{b.slice(3)}</h2> : <p key={i}>{b}</p>))}</div>
      </div>
    </article>
  );
}
