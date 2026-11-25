"use client";
// Create / edit one Instagram automation (an automation_rules row; POST/PATCH /automations validates it server-side).
import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Drawer } from "@/components/ui/kit";
import { MediaPicker } from "./MediaPicker";
import { FormQuestions } from "./FormQuestions";
import { SequenceSteps, sequenceTotal } from "./SequenceSteps";
import { AttachmentField, DelayField, SharePostField } from "./AutomationExtras";
import { TEMPLATES, type IgTemplate } from "./templates";
import { DEFAULT_ACKS, DEFAULT_FORM, DEFAULT_SUGGEST, IG_ACTION, SEQUENCE_WINDOW_MINUTES, TRIGGERS, triggerMeta, type IgActionConfig, type IgAttachment, type IgForm, type IgRule, type IgSharePost, type IgSequenceStep, type IgSuggestMore, type IgTrigger, type IgTriggerConfig } from "./automationTypes";

const field = "min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] sm:text-[14.5px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none";
const area = cn(field, "min-h-[88px] py-2.5 leading-relaxed");
const COMMENT_TRIGGERS: string[] = ["ig_comment_received", "ig_live_comment_received"];
// "Public reply only" sends no DM, so the default replies must not say "check your DMs".
const PUBLIC_ONLY_ACKS = ["Thank you!", "Thanks for the love!", "So glad you like it!"];

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="border-b border-[var(--haip-border)] py-4 first:pt-0 last:border-b-0">
      <h3 className="text-[14.5px] font-semibold text-[var(--haip-fg)]">{title}</h3>
      {hint && <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">{hint}</p>}
      <div className="mt-3 grid gap-3">{children}</div>
    </section>
  );
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="mt-1 size-5 shrink-0 accent-[var(--primary)]" />
      <span><span className="text-[14.5px] font-medium">{label}</span>{hint && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{hint}</span>}</span>
    </label>
  );
}

function Keywords({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const words = draft.split(",").map(w => w.trim()).filter(Boolean).filter(w => !value.includes(w));
    if (words.length) onChange([...value, ...words]);
    setDraft("");
  };
  return (
    <div>
      <div className="flex gap-2">
        <input className={field} value={draft} placeholder={placeholder} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} onBlur={add} />
        <button type="button" onClick={add} className="min-h-11 shrink-0 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Add</button>
      </div>
      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {value.map(k => (
            <span key={k} className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-primary-tint)] py-1 pl-3 pr-1 text-[13px] font-medium text-primary">
              {k}
              <button type="button" aria-label={`Remove ${k}`} onClick={() => onChange(value.filter(x => x !== k))} className="flex size-7 items-center justify-center rounded-full"><X size={13} /></button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Bubble({ who, children, button }: { who: "them" | "you"; children: ReactNode; button?: string }) {
  return (
    <div className={cn("flex", who === "you" ? "justify-end" : "justify-start")}>
      <div className={cn("max-w-[85%] rounded-[16px] px-3 py-2 text-[13px] leading-snug",
        who === "you" ? "bg-primary text-primary-foreground" : "bg-[var(--haip-surface)] text-[var(--haip-fg)]")}>
        <p className="whitespace-pre-wrap">{children}</p>
        {button && <span className="mt-2 block rounded-[10px] bg-[var(--haip-card)] px-3 py-1.5 text-center text-[12.5px] font-semibold text-primary">{button}</span>}
      </div>
    </div>
  );
}

const sample = (t: string) => (t || "").replaceAll("{first_name}", "Asha");

export function AutomationBuilder({ open, onOpenChange, initial, preset, copyFrom }: {
  open: boolean; onOpenChange: (o: boolean) => void; initial?: IgRule | null;
  /** A new automation that starts as a copy of this one (the Posts view's "Copy one…"), saved as its own rule. */
  copyFrom?: IgRule | null;
  /** A new automation for this post (the dashboard's "Add" on a post with no automation). */
  preset?: { id: string; thumb?: string; caption?: string } | null;
}) {
  const qc = useQueryClient();
  const presetMedia = preset ? { media_id: preset.id, media_thumb: preset.thumb, media_caption: preset.caption } : {};
  const tc0: IgTriggerConfig = initial?.trigger_config
    ?? (copyFrom ? { ...copyFrom.trigger_config, media_bound_at: undefined, ...(preset ? { scope: "post" as const, ...presetMedia } : {}) }
      : { scope: "post", keywords: [], ...presetMedia });
  const ac0: IgActionConfig = initial?.action_config ?? copyFrom?.action_config ?? { message: "" };
  const [name, setName] = useState(initial?.name ?? (copyFrom ? `${copyFrom.name} (copy)` : ""));
  const [trigger, setTrigger] = useState<IgTrigger>(((initial ?? copyFrom)?.trigger as IgTrigger) ?? "ig_comment_received");
  const [scope, setScope] = useState<"post" | "any" | "next_post">(tc0.scope ?? (tc0.media_id ? "post" : "any"));
  const [media, setMedia] = useState({ id: tc0.media_id ?? "", thumb: tc0.media_thumb ?? "", caption: tc0.media_caption ?? "" });
  const [keywords, setKeywords] = useState<string[]>(tc0.keywords ?? []);
  const [excludes, setExcludes] = useState<string[]>(tc0.exclude_keywords ?? []);
  const [replyAll, setReplyAll] = useState(!!tc0.reply_all);
  const [mention, setMention] = useState(!!tc0.mention_only);
  const [acks, setAcks] = useState<string[]>(ac0.public_ack_pool?.length ? ac0.public_ack_pool : DEFAULT_ACKS);
  const [message, setMessage] = useState(ac0.message ?? "");
  const [withButton, setWithButton] = useState(!!ac0.button?.url);
  const [button, setButton] = useState({ title: ac0.button?.title ?? "See details", url: ac0.button?.url ?? "" });
  const [opener, setOpener] = useState(ac0.opener ?? "Hi {first_name}! Tap below and I'll send it over 👇");
  const [openerButton, setOpenerButton] = useState(ac0.opener_button ?? "Send it");
  const [gate, setGate] = useState({ enabled: false, ask_text: "Please follow us first, then tap the button below 👇", button_title: "I'm following", max_asks: 3, send_anyway: true, ...(ac0.follow_gate ?? {}) });
  const [once, setOnce] = useState(ac0.once_per_person ?? true);
  const [form, setForm] = useState<IgForm>(ac0.form?.questions?.length ? ac0.form : DEFAULT_FORM);
  const [sequence, setSequence] = useState<IgSequenceStep[]>(ac0.sequence ?? []);
  const [suggest, setSuggest] = useState<IgSuggestMore>({ ...DEFAULT_SUGGEST, ...(ac0.suggest_more ?? {}) });
  const [sendDm, setSendDm] = useState(ac0.send_dm ?? true);
  const [openerAlways, setOpenerAlways] = useState(!!ac0.opener_always);
  const [oncePerPost, setOncePerPost] = useState(!!ac0.once_per_post);
  const [delay, setDelay] = useState(ac0.delay_seconds ?? 0);
  const [attachment, setAttachment] = useState<IgAttachment | null>(ac0.attachment ?? null);
  const [sharePost, setSharePost] = useState<IgSharePost>(ac0.share_post ?? { enabled: false });
  const [sendExisting, setSendExisting] = useState(false);
  const [error, setError] = useState("");

  const isComment = COMMENT_TRIGGERS.includes(trigger);
  const keywordOptional = trigger === "ig_story_mention_received" || trigger === "ig_ad_chat_started";
  const dm = !isComment || sendDm; // comments can be "public reply only"
  // Comments need a tap before Instagram allows more messages (a photo, a shared post, a form); an open chat (DM keyword,
  // story reply, ad) starts the form at once.
  const needsTap = gate.enabled || openerAlways || (form.enabled ? isComment : withButton) || (isComment && (!!attachment || sharePost.enabled));
  const matchMode = mention ? "mention" : replyAll ? "all" : "keywords";

  const applyTemplate = (t: IgTemplate) => {
    setTrigger(t.trigger); setName(t.name); setKeywords(t.keywords); setReplyAll(!!t.replyAll);
    if (t.acks) setAcks(t.acks);
    setMessage(t.message);
    setWithButton(!!t.button); if (t.button) setButton(t.button);
    setForm(t.form ?? { ...form, enabled: false });
    setSequence(t.sequence ?? []);
    setSuggest({ ...suggest, enabled: !!t.suggest });
    if (t.trigger === "ig_comment_received" && !preset) setScope("any");
  };

  const save = useMutation({
    mutationFn: () => {
      const trigger_config: IgTriggerConfig = {
        keywords, exclude_keywords: excludes, reply_all: keywordOptional ? true : replyAll && !mention, mention_only: isComment && mention,
        scope: isComment && trigger === "ig_comment_received" ? scope : "any",
        ...(isComment && trigger === "ig_comment_received" && scope === "post" && media.id
          ? { media_id: media.id, media_thumb: media.thumb || undefined, media_caption: media.caption.slice(0, 300) || undefined } : {}),
        ...(scope === "next_post" && tc0.scope === "next_post" && tc0.media_id ? { media_id: tc0.media_id, media_bound_at: tc0.media_bound_at } : {}),
      };
      const action_config: IgActionConfig = {
        message, send_dm: dm, button: withButton ? button : null, opener, opener_button: openerButton, opener_always: openerAlways,
        once_per_post: oncePerPost, delay_seconds: delay, attachment,
        share_post: sharePost.enabled ? { enabled: true, media_id: sharePost.media_id || null, media_thumb: sharePost.media_thumb || null } : { enabled: false },
        public_ack_pool: isComment ? acks.filter(a => a.trim()) : [], follow_gate: gate, once_per_person: once,
        form: { enabled: form.enabled, questions: form.questions.map(q => ({ ...q, text: q.text.trim(), options: (q.options ?? []).filter(Boolean) })) },
        suggest_more: { ...suggest, prompt: suggest.prompt.trim() || DEFAULT_SUGGEST.prompt, button_title: suggest.button_title.trim() || DEFAULT_SUGGEST.button_title },
        sequence: sequence.map(s => ({ ...s, text: s.text.trim(), button: s.button?.url.trim() ? { title: s.button.title, url: s.button.url.trim() } : null })),
      };
      const body = { name: name.trim() || triggerMeta(trigger)?.short || "Instagram automation", trigger, action: IG_ACTION, trigger_config, action_config };
      return initial ? api.patch(`/automations/${initial.id}`, body) : api.post("/automations", { ...body, is_active: true });
    },
    onSuccess: async res => {
      if (sendExisting && trigger === "ig_comment_received" && res?.data?.id) {
        await api.post(`/instagram/automations/${res.data.id}/send-existing`).catch(() => undefined); // runs in the background
      }
      qc.invalidateQueries({ queryKey: ["automations"] });
      onOpenChange(false);
    },
    onError: (e: { response?: { data?: { detail?: string } } }) => setError(e?.response?.data?.detail || "Couldn't save. Check the fields and try again."),
  });

  const submit = () => {
    setError("");
    if (dm && !message.trim()) return setError("Write the message people get in their DMs.");
    if (!dm && !acks.some(a => a.trim())) return setError("Add at least one public reply: with no DM it is the whole answer.");
    if (dm && sharePost.enabled && sharePost.media_id === "") return setError("Pick the post to share.");
    if (isComment && trigger === "ig_comment_received" && scope === "post" && !media.id) return setError("Pick the post or reel.");
    if (!keywordOptional && !replyAll && !mention && keywords.length === 0) return setError("Add a keyword, or turn on “Reply to every comment”.");
    if (withButton && !/^https:\/\/\S+$/.test(button.url.trim())) return setError("The button link must start with https://");
    if (dm && form.enabled && form.questions.filter(q => q.key === "phone").length > 1) return setError("Ask for the WhatsApp number only once.");
    if (form.enabled && form.questions.some(q => !q.text.trim())) return setError("Write the text for every question.");
    if (sequence.some(s => !s.text.trim())) return setError("Write the text for every follow-up, or remove the empty one.");
    if (sequence.some(s => s.button && !/^https:\/\/\S+$/.test(s.button.url.trim()))) return setError("Follow-up links must start with https://");
    if (sequenceTotal(sequence) > SEQUENCE_WINDOW_MINUTES) return setError("The follow-ups must all go out within 23 hours.");
    save.mutate();
  };

  return (
    <Drawer open={open} onOpenChange={onOpenChange} wide title={initial ? "Edit automation" : "New Instagram automation"}
      description="When someone engages, HAIP replies for you, once per person."
      footer={
        <div className="flex w-full flex-col gap-2">
          {error && <p role="alert" className="text-[13.5px] text-[var(--haip-status-danger-fg)]">{error}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => onOpenChange(false)} className="min-h-11 flex-1 rounded-full border border-[var(--haip-border)] text-[14.5px] font-medium">Cancel</button>
            <button type="button" onClick={submit} disabled={save.isPending}
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-full bg-primary text-[14.5px] font-semibold text-primary-foreground transition-transform active:scale-[0.97] disabled:opacity-60">
              {save.isPending && <Loader2 size={15} className="animate-spin" />} {initial ? "Save changes" : "Turn on"}
            </button>
          </div>
        </div>
      }>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div>
          {!initial && (
            <Section title="Start from a template" hint="Fills in everything below. Change anything you like.">
              <div className="flex flex-wrap gap-2">
                {TEMPLATES.map(t => (
                  <button key={t.key} type="button" onClick={() => applyTemplate(t)} title={t.hint}
                    className="min-h-11 rounded-full border border-[var(--haip-border)] px-4 text-[13.5px] font-medium hover:border-primary">{t.label}</button>
                ))}
              </div>
            </Section>
          )}

          <Section title="When">
            <div className="grid grid-cols-2 gap-2">
              {TRIGGERS.map(t => (
                <button key={t.value} type="button" onClick={() => setTrigger(t.value)} aria-pressed={trigger === t.value}
                  className={cn("min-h-11 rounded-[12px] border px-3 py-2 text-left text-[13.5px] font-medium leading-tight",
                    trigger === t.value ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>
                  {t.label}
                </button>
              ))}
            </div>
            <p className="text-[13px] text-[var(--haip-fg-subtle)]">{triggerMeta(trigger)?.hint}</p>
          </Section>

          {trigger === "ig_comment_received" && (
            <Section title="Which posts">
              <div className="flex flex-wrap gap-2">
                {([["post", "A specific post or reel"], ["any", "Any post"], ["next_post", "My next post"]] as const).map(([v, l]) => (
                  <button key={v} type="button" onClick={() => setScope(v)} aria-pressed={scope === v}
                    className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium",
                      scope === v ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{l}</button>
                ))}
              </div>
              {scope === "post" && <MediaPicker value={media.id} onPick={m => setMedia({ id: m.id, thumb: m.thumbnail ?? "", caption: m.caption })} />}
              {scope === "next_post" && (
                <p className="text-[13px] text-[var(--haip-fg-subtle)]">
                  {tc0.scope === "next_post" && tc0.media_id ? "Now running on the post you published after creating it." : "Starts on the first post or reel you publish after turning this on."}
                </p>
              )}
            </Section>
          )}

          {!keywordOptional && (
            <Section title="Keywords" hint="Whole words, any capitalisation. PRICE matches “price?” and “Price pls”.">
              {isComment ? (
                <div className="flex flex-wrap gap-2">
                  {([["keywords", "Keywords"], ["all", "Every comment"], ["mention", "Tags someone (@)"]] as const).map(([v, l]) => (
                    <button key={v} type="button" aria-pressed={matchMode === v}
                      onClick={() => { setReplyAll(v === "all"); setMention(v === "mention"); }}
                      className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium",
                        matchMode === v ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{l}</button>
                  ))}
                </div>
              ) : <Toggle checked={replyAll} onChange={setReplyAll} label="Reply to every message" hint="No keyword needed." />}
              {mention && <p className="text-[13px] text-[var(--haip-fg-subtle)]">Replies when a comment tags another account, e.g. “@meera look at this”. Good for “tag a friend” posts.</p>}
              {!replyAll && !mention && <Keywords value={keywords} onChange={setKeywords} placeholder="e.g. PRICE, BOOK, LINK" />}
              <details className="text-[14px]">
                <summary className="min-h-11 cursor-pointer py-2 font-medium text-[var(--haip-fg-muted)]">Skip messages containing…</summary>
                <Keywords value={excludes} onChange={setExcludes} placeholder="e.g. scam, refund" />
              </details>
            </Section>
          )}

          {isComment && (
            <Section title="Public reply under the comment" hint="One is picked at random each time, so replies don't look copy-pasted.">
              <Toggle checked={!sendDm} label="Public reply only, no DM" hint="HAIP answers under the comment and sends nothing in the DMs."
                onChange={v => {
                  setSendDm(!v);
                  const same = (a: string[], b: string[]) => a.join("|") === b.join("|");
                  if (v && same(acks, DEFAULT_ACKS)) setAcks(PUBLIC_ONLY_ACKS);
                  if (!v && same(acks, PUBLIC_ONLY_ACKS)) setAcks(DEFAULT_ACKS);
                }} />
              {acks.map((a, i) => (
                <div key={i} className="flex gap-2">
                  <input className={field} value={a} maxLength={300} onChange={e => setAcks(acks.map((x, j) => (j === i ? e.target.value : x)))} />
                  <button type="button" aria-label="Remove reply" onClick={() => setAcks(acks.filter((_, j) => j !== i))} className="flex size-11 shrink-0 items-center justify-center rounded-full border border-[var(--haip-border)]"><X size={15} /></button>
                </div>
              ))}
              {acks.length < 10 && (
                <button type="button" onClick={() => setAcks([...acks, ""])} className="inline-flex min-h-11 items-center gap-1.5 self-start text-[14px] font-medium text-primary"><Plus size={15} /> Add a variation</button>
              )}
            </Section>
          )}

          {dm && <>
          <Section title="Collect details in the DM" hint="HAIP asks a few short questions, one at a time. When the WhatsApp number arrives, the person becomes a lead.">
            <Toggle checked={form.enabled} onChange={v => setForm({ ...form, enabled: v })} label="Ask questions before the final message"
              hint="Typed answers work as well as the tap options. Asking for a person or saying stop ends it." />
            {form.enabled && <FormQuestions value={form.questions} onChange={questions => setForm({ ...form, questions })} />}
          </Section>

          <Section title={form.enabled ? "After the last answer" : "The DM"} hint={form.enabled ? "Use {first_name} for their name and {agent_name} for the person the lead is assigned to." : "Use {first_name} for their name."}>
            <textarea className={area} value={message} maxLength={900} onChange={e => setMessage(e.target.value)}
              placeholder="Hi {first_name}! Here are our packages and prices…" />
            <Toggle checked={withButton} onChange={setWithButton} label="Add a link button" hint="Clicks are counted in the stats." />
            {withButton && (
              <div className="grid gap-2 sm:grid-cols-[160px_1fr]">
                <input className={field} value={button.title} maxLength={20} onChange={e => setButton({ ...button, title: e.target.value })} placeholder="Button text" aria-label="Button text" />
                <input className={field} value={button.url} onChange={e => setButton({ ...button, url: e.target.value })} placeholder="https://…" inputMode="url" aria-label="Button link" />
              </div>
            )}
            <AttachmentField value={attachment} onChange={setAttachment} />
            <Toggle checked={sharePost.enabled} onChange={v => setSharePost(v ? { enabled: true, media_id: isComment ? null : "" } : { enabled: false })}
              label="Share one of your posts" hint="Sent after the message. Instagram only shares your own posts and reels." />
            {sharePost.enabled && <SharePostField value={sharePost} onChange={setSharePost} isComment={isComment} />}
            <Toggle checked={openerAlways} onChange={setOpenerAlways} label="Start with an opening message"
              hint="The first DM asks them to tap; the message above follows the tap." />
            {needsTap && (
              <div className="rounded-[12px] bg-[var(--haip-surface)] p-3">
                <p className="text-[13px] text-[var(--haip-fg-muted)]">{openerAlways ? "The opening message:" : "Instagram only allows a link, photo or post after they reply, so the first DM asks them to tap:"}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_140px]">
                  <input className={field} value={opener} maxLength={640} onChange={e => setOpener(e.target.value)} aria-label="First message" />
                  <input className={field} value={openerButton} maxLength={20} onChange={e => setOpenerButton(e.target.value)} aria-label="Tap button text" />
                </div>
              </div>
            )}
          </Section>

          <Section title="Suggest more" hint="After the final message, offer a button that shows your stays or packages as swipeable cards. Cards never show prices.">
            <Toggle checked={suggest.enabled} onChange={v => setSuggest({ ...suggest, enabled: v })} label="Offer more options"
              hint="“I'm interested” on a card notes their pick on the lead and hands the chat to your team." />
            {suggest.enabled && (
              <div className="grid gap-2">
                <div className="flex flex-wrap gap-2">
                  {([["stays", "Our stays"], ["packages", "Our packages"]] as const).map(([v, l]) => (
                    <button key={v} type="button" onClick={() => setSuggest({ ...suggest, source: v })} aria-pressed={suggest.source === v}
                      className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium",
                        suggest.source === v ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{l}</button>
                  ))}
                </div>
                <div className="grid gap-2 sm:grid-cols-[1fr_160px]">
                  <input className={field} value={suggest.prompt} maxLength={300} onChange={e => setSuggest({ ...suggest, prompt: e.target.value })} aria-label="Offer message" />
                  <input className={field} value={suggest.button_title} maxLength={20} onChange={e => setSuggest({ ...suggest, button_title: e.target.value })} aria-label="Offer button text" />
                </div>
              </div>
            )}
          </Section>

          <Section title="Follow-up messages" hint={isComment ? "Sent after the final message, which goes out once they tap. Up to 3." : "Sent after the final message. Up to 3."}>
            <SequenceSteps value={sequence} onChange={setSequence} />
          </Section>

          <Section title="Ask to follow first">
            <Toggle checked={gate.enabled} onChange={v => setGate({ ...gate, enabled: v })} label="Only send after they follow"
              hint="HAIP checks with Instagram whether they follow you." />
            {gate.enabled && (
              <>
                <textarea className={area} value={gate.ask_text} maxLength={640} onChange={e => setGate({ ...gate, ask_text: e.target.value })} aria-label="Follow request message" />
                <div className="grid gap-2 sm:grid-cols-2">
                  <input className={field} value={gate.button_title} maxLength={20} onChange={e => setGate({ ...gate, button_title: e.target.value })} aria-label="Follow button text" />
                  <select className={field} value={gate.max_asks} onChange={e => setGate({ ...gate, max_asks: Number(e.target.value) })} aria-label="How many times to ask">
                    {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>Ask up to {n} {n === 1 ? "time" : "times"}</option>)}
                  </select>
                </div>
                <Toggle checked={gate.send_anyway} onChange={v => setGate({ ...gate, send_anyway: v })} label="Send anyway after the last ask" />
              </>
            )}
          </Section>

          </>}

          <Section title="Details">
            <input className={field} value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="Name, e.g. PRICE reel – monsoon offer" aria-label="Automation name" />
            <Toggle checked={once} onChange={setOnce} label="Only once per person" hint="Someone who comments twice gets one reply." />
            {once && isComment && scope !== "post" && (
              <Toggle checked={oncePerPost} onChange={setOncePerPost} label="Once per post, not once overall" hint="The same person gets a reply again on a different post." />
            )}
            <label className="grid gap-1 text-[14px] font-medium">Reply time
              <DelayField value={delay} onChange={setDelay} className={field} />
            </label>
            {trigger === "ig_comment_received" && (
              <Toggle checked={sendExisting} onChange={setSendExisting} label="Also answer comments from the last 7 days"
                hint="When you save, HAIP replies to matching comments the post already has. Instagram allows this for 7 days." />
            )}
          </Section>
        </div>

        <aside aria-label="Preview" className="lg:sticky lg:top-0 lg:self-start">
          <p className="mb-2 text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[var(--haip-fg-subtle)]">Preview</p>
          <div className="grid gap-2 rounded-[20px] border border-[var(--haip-border)] bg-[var(--haip-card)] p-3">
            {isComment && <Bubble who="them">{keywords[0] ? keywords[0].toUpperCase() : "Love this! 😍"}</Bubble>}
            {isComment && <p className="px-1 text-[12px] text-[var(--haip-fg-subtle)]">Your reply: “{acks.find(a => a.trim()) || DEFAULT_ACKS[0]}”</p>}
            {!isComment && <Bubble who="them">{trigger === "ig_story_mention_received" ? "Mentioned you in their story" : keywords[0] || "Hi!"}</Bubble>}
            {dm && needsTap && <Bubble who="you" button={openerButton}>{sample(opener)}</Bubble>}
            {dm && <>
              {gate.enabled && <Bubble who="you" button={gate.button_title}>{sample(gate.ask_text)}</Bubble>}
              {form.enabled && form.questions.slice(0, 3).map((q, i) => <Bubble key={i} who="you" button={q.options?.slice(0, 3).join(" · ") || undefined}>{q.text || "Question…"}</Bubble>)}
              <Bubble who="you" button={withButton ? button.title : undefined}>{sample(message).replaceAll("{agent_name}", "Priya") || "Your message…"}</Bubble>
              {attachment && <Bubble who="you">{attachment.kind === "video" ? "Video" : "Photo"}{attachment.filename ? ` · ${attachment.filename}` : ""}</Bubble>}
              {sharePost.enabled && <Bubble who="you">Shared post</Bubble>}
              {suggest.enabled && <Bubble who="you" button={suggest.button_title}>{suggest.prompt}</Bubble>}
              {sequence.map((s, i) => <Bubble key={`seq-${i}`} who="you" button={s.button?.title || undefined}>{sample(s.text) || "Follow-up…"}</Bubble>)}
            </>}
            {!dm && <p className="px-1 text-[12px] text-[var(--haip-fg-subtle)]">No DM is sent.</p>}
          </div>
        </aside>
      </div>
    </Drawer>
  );
}
