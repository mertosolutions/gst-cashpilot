"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Keyboard, MessageCircle, Mic, MicOff, Send, Sparkles, Volume2, VolumeX, X } from "lucide-react";
import { ChatResults, FilterChips, VoiceAnswer } from "@/components/chat/VoiceResults";
import Markdown from "@/components/chat/Markdown";
import ItemDrawer from "@/components/reconciliation/ItemDrawer";
import VendorDrawer from "@/components/dashboard/VendorDrawer";
import { api, wsAuthQuery } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { LiveMessage, LiveState, LiveVoice, liveSupported } from "@/lib/live";
import { LANGS, canSpeak, speak, stopSpeaking, useSpeechRecognition } from "@/lib/speech";

interface Msg { id: string; role: "user" | "agent" | "error"; text: string; voice?: VoiceAnswer; agent?: string; live?: boolean }
const uid = () => Math.random().toString(36).slice(2, 10);

function Bars({ state }: { state: LiveState }) {
  return (
    <span className="flex h-5 items-end gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className={clsx("w-[3px] rounded-full", state === "speaking" ? "bg-brand-600" : "bg-ok-500", state === "connecting" ? "h-1.5" : "animate-pulse")}
          style={{ height: state === "connecting" ? 6 : 6 + ((i * 7 + 5) % 14), animationDelay: `${i * 110}ms` }} />
      ))}
    </span>
  );
}

/** Floating chat. Type or talk. Talking uses Gemini Live (real-time voice, any Indian language) when Gemini is on, otherwise the browser's speech recognition.
    Data questions are answered from your saved results; open questions go to the Google ADK agents. */
export default function ChatWidget() {
  const { month, months, refresh, status } = useApp();
  const label = months.find((m) => m.month === month)?.label ?? "this month";
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [lang, setLang] = useState("en-IN");
  const [voiceReplies, setVoiceReplies] = useState(true);
  const [suggest, setSuggest] = useState<string[]>([]);
  const [openMatch, setOpenMatch] = useState<string | null>(null);
  const [openVendor, setOpenVendor] = useState<string | null>(null);
  const [liveState, setLiveState] = useState<LiveState>("idle");
  const end = useRef<HTMLDivElement>(null);
  const live = useRef<LiveVoice | null>(null);
  const liveUser = useRef<string | null>(null);
  const liveAssist = useRef<string | null>(null);
  const useLive = !!status?.gemini_configured && liveSupported();

  useEffect(() => { try { setLang(localStorage.getItem("cashpilot.voiceLang") || "en-IN"); setVoiceReplies(localStorage.getItem("cashpilot.voiceReplies") !== "off"); } catch { /* ignore */ } }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy, open, liveState]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") { stopSpeaking(); setOpen(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    if (!open || !month) return;
    api.get<string[]>("/voice/suggestions", { month }).then((s) => setSuggest(s.slice(0, 3))).catch(() => setSuggest([]));
  }, [open, month]);
  useEffect(() => () => { live.current?.stop(); }, []);

  const patch = (id: string, fn: (m: Msg) => Msg) => setMsgs((all) => all.map((m) => (m.id === id ? fn(m) : m)));

  /* ---------- typed / browser-speech questions ---------- */
  const send = useCallback(async (question: string, viaVoice = false) => {
    const text = question.trim();
    if (text.length < 2 || busy) return;
    setQ("");
    if (live.current && (liveState === "listening" || liveState === "speaking")) {
      live.current.sendText(text);
      setMsgs((m) => [...m, { id: uid(), role: "user", text }]);
      return;
    }
    setBusy("Searching your data and the GST rules, then asking Gemini..."); setMsgs((m) => [...m, { id: uid(), role: "user", text }]);
    try {
      const history = msgs.filter((x) => (x.role === "user" || x.role === "agent") && x.text).slice(-6).map((x) => ({ role: x.role === "user" ? "user" : "assistant", text: x.text }));
      const v = await api.post<VoiceAnswer>("/voice/query", { text, lang, month, history }, { month });
      if (v.intent !== "unknown" || v.engine.startsWith("Gemini")) {  // Gemini writes the reply; the exact search only supplies the data and the cards
        setMsgs((m) => [...m, { id: uid(), role: "agent", text: v.answer, voice: v }]);
        if (viaVoice && voiceReplies && canSpeak()) speak(v.spoken, v.spoken_language === "en" ? "en-IN" : lang);
      } else {
        setBusy("Asking the Google ADK agents...");
        const r = await api.post<{ answer: string; agent: string }>("/copilot/ask", { question: v.english ?? text, month });
        setMsgs((m) => [...m, { id: uid(), role: "agent", text: r.answer, agent: r.agent }]);
        if (viaVoice && voiceReplies && canSpeak()) speak(r.answer.replace(/[*_`#]/g, ""), "en-IN");
      }
    } catch (e) { setMsgs((m) => [...m, { id: uid(), role: "error", text: (e as Error).message }]); }
    finally { setBusy(null); }
  }, [busy, lang, liveState, month, voiceReplies, msgs]);

  /* ---------- Gemini Live ---------- */
  const onLive = useCallback((m: LiveMessage) => {
    if (m.type === "user_transcript") {
      if (liveAssist.current) { liveAssist.current = null; liveUser.current = null; }
      if (!liveUser.current) { const id = uid(); liveUser.current = id; setMsgs((all) => [...all, { id, role: "user", text: m.text.trimStart(), live: true }]); }
      else patch(liveUser.current, (x) => ({ ...x, text: x.text + m.text }));
    } else if (m.type === "assistant_transcript") {
      if (!liveAssist.current) { const id = uid(); liveAssist.current = id; setMsgs((all) => [...all, { id, role: "agent", text: m.text.trimStart(), live: true, agent: "Gemini Live" }]); }
      else patch(liveAssist.current, (x) => ({ ...x, text: x.text + m.text }));
    } else if (m.type === "results") {
      const data = m.data as VoiceAnswer;
      if (!liveAssist.current) { const id = uid(); liveAssist.current = id; setMsgs((all) => [...all, { id, role: "agent", text: "", voice: data, live: true, agent: "Gemini Live" }]); }
      else patch(liveAssist.current, (x) => ({ ...x, voice: data }));
    } else if (m.type === "error") {
      setMsgs((all) => [...all, { id: uid(), role: "error", text: m.message }]);
      live.current?.stop();
    }
  }, []);

  async function startLive() {
    stopSpeaking(); liveUser.current = null; liveAssist.current = null;
    const lv = new LiveVoice(onLive, setLiveState);
    live.current = lv;
    try { await lv.start({ month, authQuery: await wsAuthQuery() }); }
    catch (e) { setMsgs((all) => [...all, { id: uid(), role: "error", text: (e as Error).message }]); }
  }
  const stopLive = () => { live.current?.stop(); live.current = null; };

  /* ---------- fallback: browser speech recognition ---------- */
  const mic = useSpeechRecognition(lang, (t) => send(t, true));
  const liveOn = liveState !== "idle";
  const toggleMic = () => {
    if (useLive) { if (liveOn) stopLive(); else startLive(); return; }
    if (mic.listening) mic.stop(); else { stopSpeaking(); mic.start(); }
  };
  const micActive = useLive ? liveOn : mic.listening;
  const micOk = useLive || mic.supported;
  const changeLang = (l: string) => { setLang(l); try { localStorage.setItem("cashpilot.voiceLang", l); } catch { /* ignore */ } };
  const toggleReplies = () => { stopSpeaking(); setVoiceReplies((v) => { try { localStorage.setItem("cashpilot.voiceReplies", v ? "off" : "on"); } catch { /* ignore */ } return !v; }); };
  const placeholder = liveOn ? "Speak, or type here" : mic.listening ? (mic.interim ? `“${mic.interim}”` : "Listening...") : "Type, or tap the mic and talk";
  const liveText = liveState === "connecting" ? "Connecting to Gemini Live..." : liveState === "speaking" ? "CashPilot is speaking..." : "Listening. Talk in any language.";

  return (
    <>
      {open && (
        <section role="dialog" aria-label="Ask CashPilot"
          className="fixed z-[45] bottom-24 right-4 sm:right-6 w-[calc(100vw-2rem)] sm:w-[430px] max-h-[min(700px,calc(100vh-8rem))] flex flex-col rounded-2xl bg-white border border-slate-200 shadow-pop overflow-hidden">
          <header className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-brand-600 to-brand-700 text-white">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-white/15"><Sparkles size={16} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-tight">Ask CashPilot</p>
              <p className="text-[11px] text-white/80 leading-tight truncate">{liveOn ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-green-300" /> Gemini Live · Multilingual (EN/HI/TA)</span> : `Google ADK Multi-Agent · ${label}`}</p>
            </div>
            {!useLive && <select value={lang} onChange={(e) => changeLang(e.target.value)} aria-label="Speaking language" className="max-w-[118px] rounded-lg border-0 bg-white/15 px-2 py-1 text-xs text-white focus:outline-none [&>option]:text-ink-900">{LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}</select>}
            {!useLive && <button onClick={toggleReplies} className="p-1.5 rounded-lg hover:bg-white/15" aria-label={voiceReplies ? "Turn spoken replies off" : "Turn spoken replies on"} aria-pressed={voiceReplies}>{voiceReplies ? <Volume2 size={16} /> : <VolumeX size={16} />}</button>}
            <button onClick={() => { stopSpeaking(); stopLive(); setOpen(false); }} className="p-1.5 rounded-lg hover:bg-white/15" aria-label="Close chat"><X size={16} /></button>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-slate-50/60 min-h-[220px]">
            {!msgs.length && (
              <div className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold">Hi, I'm CashPilot</p>
                  <span className="chip bg-brand-50 text-brand-700 text-[10px]">ADK Multi-Agent</span>
                </div>
                <p className="mt-1 text-xs text-ink-600">Specialist agents: <strong>Tax Reconciliation</strong> · <strong>Vendor Communication</strong> · <strong>GST Legal RAG</strong>.</p>
                <div className="mt-3 flex flex-col gap-2">
                  {[
                    `Which vendors block my credit in ${label}?`,
                    `Notify defaulting vendors for ${label}`,
                    `What is my cash payable for ${label} in both cases?`,
                    `Why is the largest at-risk invoice blocked under GST rules?`,
                  ].map((s) => (
                    <button key={s} onClick={() => send(s)} className="text-left rounded-xl border border-brand-500/25 bg-brand-50/50 px-3 py-2 text-[12px] font-medium text-brand-700 hover:bg-brand-50 transition">{s}</button>
                  ))}
                </div>
                <p className="mt-3 text-[11px] text-ink-500">{useLive ? "🎙️ Tap the mic to talk to Gemini Live in your own language (Tamil, Hindi, English)." : "Tap the mic to speak. Your browser turns your voice into text."}</p>
              </div>
            )}
            {msgs.map((m) => (
              <div key={m.id} className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={clsx("max-w-[92%] rounded-2xl px-3.5 py-2 text-sm", m.role === "user" ? "bg-brand-600 text-white rounded-br-md whitespace-pre-wrap" : m.role === "error" ? "bg-warn-50 text-warn-700 rounded-bl-md" : "bg-white border border-slate-200 text-ink-900 rounded-bl-md")}>
                  {m.voice && m.voice.intent !== "help" && <FilterChips filters={m.voice.filters} />}
                  {m.voice?.english && <p className="mb-1 text-[11px] text-ink-500">Understood as: “{m.voice.english}”</p>}
                  {m.role === "agent" ? (m.text ? <Markdown text={m.text} /> : null) : <p className="whitespace-pre-wrap">{m.text}</p>}
                  {m.voice?.notes.map((n) => <p key={n} className="mt-1.5 rounded-lg bg-warn-50 p-1.5 text-[11px] text-warn-700">{n}</p>)}
                  {m.voice && <ChatResults a={m.voice} onInvoice={setOpenMatch} onVendor={setOpenVendor} onAsk={(x) => send(x)} />}
                  {m.role === "agent" && (m.voice || m.agent) && (
                    <div className="mt-1.5 flex items-center gap-2 text-[10px] text-ink-500">
                      <span>{m.live ? "Gemini Live" : m.voice ? m.voice.engine : m.agent}</span>
                      {!m.live && canSpeak() && m.text && <button className="ml-auto flex items-center gap-1 hover:text-brand-700" onClick={() => { stopSpeaking(); speak((m.voice?.spoken ?? m.text).replace(/[*_`#]/g, ""), m.voice && m.voice.spoken_language !== "en" ? lang : "en-IN"); }} aria-label="Read this reply aloud"><Volume2 size={12} /> Read aloud</button>}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="flex"><div className="rounded-2xl rounded-bl-md bg-white border border-slate-200 px-3.5 py-2 text-sm text-ink-500 animate-pulse">{busy}</div></div>}
            {mic.error && !useLive && <p className="rounded-xl bg-warn-50 p-2 text-xs text-warn-700">{mic.error}</p>}
            <div ref={end} />
          </div>

          {liveOn && (
            <div className="flex items-center gap-3 border-t border-slate-100 bg-ok-50/70 px-4 py-2">
              <Bars state={liveState} /><span className="text-xs font-medium text-ok-700">{liveText}</span>
              <button onClick={stopLive} className="ml-auto rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-bad-700 shadow-card hover:bg-bad-50">End</button>
            </div>
          )}
          <form onSubmit={(e) => { e.preventDefault(); stopSpeaking(); send(q); }} className="flex items-center gap-2 border-t border-slate-100 bg-white p-3">
            <button type="button" onClick={toggleMic} disabled={(!!busy && !liveOn) || !micOk} aria-label={micActive ? "Stop listening" : "Talk to CashPilot"} title={micOk ? (useLive ? "Talk (Gemini Live)" : "Speak") : "Voice input needs Chrome or Edge"}
              className={clsx("grid h-10 w-10 shrink-0 place-items-center rounded-full text-white transition disabled:opacity-40 disabled:cursor-not-allowed", micActive ? "bg-bad-500 pulse" : "bg-gradient-to-br from-brand-500 to-brand-700 hover:scale-105")}>
              {micActive ? <MicOff size={17} /> : <Mic size={17} />}
            </button>
            <div className="relative flex-1"><Keyboard size={14} className="absolute left-3 top-3 text-ink-300" />
              <input autoFocus className="input !pl-8 !py-2" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} disabled={mic.listening} /></div>
            <button className="btn btn-primary !px-3" disabled={(!!busy && !liveOn) || q.trim().length < 2} aria-label="Send"><Send size={15} /></button>
          </form>
          <p className="px-4 pb-3 -mt-1 text-[10px] text-ink-500 bg-white">Read-only draft help. Nothing is filed and this is not tax advice.</p>
        </section>
      )}
      <button onClick={() => { if (open) { stopSpeaking(); stopLive(); } setOpen((o) => !o); }} aria-label={open ? "Close chat" : "Open Ask CashPilot"}
        className={clsx("fixed z-[45] bottom-6 right-4 sm:right-6 flex items-center gap-2 rounded-full pl-4 pr-5 py-3 text-sm font-medium text-white shadow-pop transition hover:scale-[1.03]",
          open ? "bg-ink-700" : "bg-gradient-to-r from-brand-600 to-brand-700")}>
        {open ? <X size={18} /> : <MessageCircle size={18} />}<span className="hidden sm:inline">{open ? "Close" : "Ask CashPilot"}</span>
      </button>
      <ItemDrawer matchId={openMatch} onClose={() => setOpenMatch(null)} onChanged={refresh} />
      <VendorDrawer gstin={openVendor} onClose={() => setOpenVendor(null)} />
    </>
  );
}
