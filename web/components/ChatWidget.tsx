"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Keyboard, MessageCircle, Mic, MicOff, Send, Sparkles, Volume2, VolumeX, X } from "lucide-react";
import { ChatResults, FilterChips, VoiceAnswer } from "@/components/chat/VoiceResults";
import ItemDrawer from "@/components/reconciliation/ItemDrawer";
import VendorDrawer from "@/components/dashboard/VendorDrawer";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { LANGS, canSpeak, speak, stopSpeaking, useSpeechRecognition } from "@/lib/speech";

interface Msg { role: "user" | "agent" | "error"; text: string; voice?: VoiceAnswer; agent?: string; spoken?: boolean }

/** Floating chat: type or speak. Data questions are answered from your saved results (exact); open questions go to the Google ADK agents. */
export default function ChatWidget() {
  const { month, months, refresh } = useApp();
  const label = months.find((m) => m.month === month)?.label ?? "this month";
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [lang, setLang] = useState("en-IN");
  const [voiceReplies, setVoiceReplies] = useState(true);
  const [suggest, setSuggest] = useState<string[]>([]);
  const [openMatch, setOpenMatch] = useState<string | null>(null);
  const [openVendor, setOpenVendor] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { try { setLang(localStorage.getItem("cashpilot.voiceLang") || "en-IN"); setVoiceReplies(localStorage.getItem("cashpilot.voiceReplies") !== "off"); } catch { /* ignore */ } }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy, open]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") { stopSpeaking(); setOpen(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    if (!open || !month) return;
    api.get<string[]>("/voice/suggestions", { month }).then((s) => setSuggest(s.slice(0, 4))).catch(() => setSuggest([]));
  }, [open, month]);

  const send = useCallback(async (question: string, viaVoice = false) => {
    const text = question.trim();
    if (text.length < 2 || busy) return;
    setQ(""); setBusy(true); setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const v = await api.post<VoiceAnswer>("/voice/query", { text, lang, month }, { month });
      if (v.intent !== "unknown") {
        setMsgs((m) => [...m, { role: "agent", text: v.answer, voice: v, spoken: viaVoice }]);
        if (viaVoice && voiceReplies && canSpeak()) speak(v.spoken, v.spoken_language === "en" ? "en-IN" : lang);
      } else {
        // not a data lookup: ask the Google ADK agents
        const r = await api.post<{ answer: string; agent: string }>("/copilot/ask", { question: v.english ?? text, month });
        setMsgs((m) => [...m, { role: "agent", text: r.answer, agent: r.agent }]);
        if (viaVoice && voiceReplies && canSpeak()) speak(r.answer, "en-IN");
      }
    } catch (e) { setMsgs((m) => [...m, { role: "error", text: (e as Error).message }]); }
    finally { setBusy(false); }
  }, [busy, lang, month, voiceReplies]);

  const mic = useSpeechRecognition(lang, (t) => send(t, true));
  const toggleMic = () => { if (mic.listening) mic.stop(); else { stopSpeaking(); mic.start(); } };
  const changeLang = (l: string) => { setLang(l); try { localStorage.setItem("cashpilot.voiceLang", l); } catch { /* ignore */ } };
  const toggleReplies = () => { stopSpeaking(); setVoiceReplies((v) => { try { localStorage.setItem("cashpilot.voiceReplies", v ? "off" : "on"); } catch { /* ignore */ } return !v; }); };
  const placeholder = mic.listening ? (mic.interim ? `“${mic.interim}”` : "Listening...") : "Type, or tap the mic and speak";

  return (
    <>
      {open && (
        <section role="dialog" aria-label="Ask CashPilot"
          className="fixed z-[45] bottom-24 right-4 sm:right-6 w-[calc(100vw-2rem)] sm:w-[430px] max-h-[min(700px,calc(100vh-8rem))] flex flex-col rounded-2xl bg-white border border-slate-200 shadow-pop overflow-hidden">
          <header className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-brand-600 to-brand-700 text-white">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-white/15"><Sparkles size={16} /></span>
            <div className="min-w-0 flex-1"><p className="text-sm font-semibold leading-tight">Ask CashPilot</p><p className="text-[11px] text-white/80 leading-tight truncate">Type or speak · {label}</p></div>
            <select value={lang} onChange={(e) => changeLang(e.target.value)} aria-label="Speaking language" className="max-w-[118px] rounded-lg border-0 bg-white/15 px-2 py-1 text-xs text-white focus:outline-none [&>option]:text-ink-900">
              {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
            <button onClick={toggleReplies} className="p-1.5 rounded-lg hover:bg-white/15" aria-label={voiceReplies ? "Turn spoken replies off" : "Turn spoken replies on"} aria-pressed={voiceReplies} title="Read replies aloud when you speak">
              {voiceReplies ? <Volume2 size={16} /> : <VolumeX size={16} />}
            </button>
            <button onClick={() => { stopSpeaking(); setOpen(false); }} className="p-1.5 rounded-lg hover:bg-white/15" aria-label="Close chat"><X size={16} /></button>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-slate-50/60 min-h-[220px]">
            {!msgs.length && (
              <div>
                <p className="text-sm text-ink-700">Hi, ask about your vendors, invoices or cash payable. I answer from your saved results, so the numbers are exact.</p>
                <div className="mt-3 flex flex-col gap-2">
                  {(suggest.length ? suggest : [`Which vendors block my credit in ${label}?`, `What is my cash payable for ${label}?`]).map((s) => (
                    <button key={s} onClick={() => send(s)} className="text-left rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-ink-700 hover:border-brand-500/50 hover:bg-brand-50/40">{s}</button>
                  ))}
                </div>
                <p className="mt-3 text-[11px] text-ink-500">Tap the mic to speak. Your browser's speech service turns your voice into text, and CashPilot only receives the text.</p>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={clsx("max-w-[92%] rounded-2xl px-3.5 py-2 text-sm", m.role === "user" ? "bg-brand-600 text-white rounded-br-md whitespace-pre-wrap" : m.role === "error" ? "bg-warn-50 text-warn-700 rounded-bl-md" : "bg-white border border-slate-200 text-ink-900 rounded-bl-md")}>
                  {m.voice && <FilterChips filters={m.voice.filters} />}
                  {m.voice?.english && <p className="mb-1 text-[11px] text-ink-500">Understood as: “{m.voice.english}”</p>}
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {m.voice && m.voice.spoken_language !== "en" && <p className="mt-1 text-[11px] text-ink-500">{m.voice.spoken}</p>}
                  {m.voice?.notes.map((n) => <p key={n} className="mt-1.5 rounded-lg bg-warn-50 p-1.5 text-[11px] text-warn-700">{n}</p>)}
                  {m.voice && <ChatResults a={m.voice} onInvoice={setOpenMatch} onVendor={setOpenVendor} />}
                  {m.role === "agent" && (
                    <div className="mt-1.5 flex items-center gap-2 text-[10px] text-ink-500">
                      <span>{m.voice ? m.voice.engine : m.agent}</span>
                      {canSpeak() && <button className="ml-auto flex items-center gap-1 hover:text-brand-700" onClick={() => { stopSpeaking(); speak(m.voice?.spoken ?? m.text, m.voice && m.voice.spoken_language !== "en" ? lang : "en-IN"); }} aria-label="Read this reply aloud"><Volume2 size={12} /> Read aloud</button>}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="flex"><div className="rounded-2xl rounded-bl-md bg-white border border-slate-200 px-3.5 py-2 text-sm text-ink-500 animate-pulse">Searching your data...</div></div>}
            {mic.error && <p className="rounded-xl bg-warn-50 p-2 text-xs text-warn-700">{mic.error}</p>}
            <div ref={end} />
          </div>

          <form onSubmit={(e) => { e.preventDefault(); stopSpeaking(); send(q); }} className="flex items-center gap-2 border-t border-slate-100 bg-white p-3">
            <button type="button" onClick={toggleMic} disabled={busy || !mic.supported} aria-label={mic.listening ? "Stop listening" : "Speak your question"} title={mic.supported ? "Speak" : "Voice input needs Chrome or Edge"}
              className={clsx("grid h-10 w-10 shrink-0 place-items-center rounded-full text-white transition disabled:opacity-40 disabled:cursor-not-allowed", mic.listening ? "bg-bad-500 pulse" : "bg-gradient-to-br from-brand-500 to-brand-700 hover:scale-105")}>
              {mic.listening ? <MicOff size={17} /> : <Mic size={17} />}
            </button>
            <div className="relative flex-1"><Keyboard size={14} className="absolute left-3 top-3 text-ink-300" />
              <input autoFocus className="input !pl-8 !py-2" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} disabled={mic.listening} /></div>
            <button className="btn btn-primary !px-3" disabled={busy || q.trim().length < 2} aria-label="Send"><Send size={15} /></button>
          </form>
          <p className="px-4 pb-3 -mt-1 text-[10px] text-ink-500 bg-white">Read-only draft help. Nothing is filed and this is not tax advice.</p>
        </section>
      )}
      <button onClick={() => { if (open) stopSpeaking(); setOpen((o) => !o); }} aria-label={open ? "Close chat" : "Open Ask CashPilot"}
        className={clsx("fixed z-[45] bottom-6 right-4 sm:right-6 flex items-center gap-2 rounded-full pl-4 pr-5 py-3 text-sm font-medium text-white shadow-pop transition hover:scale-[1.03]",
          open ? "bg-ink-700" : "bg-gradient-to-r from-brand-600 to-brand-700")}>
        {open ? <X size={18} /> : <MessageCircle size={18} />}<span className="hidden sm:inline">{open ? "Close" : "Ask CashPilot"}</span>
      </button>
      <ItemDrawer matchId={openMatch} onClose={() => setOpenMatch(null)} onChanged={refresh} />
      <VendorDrawer gstin={openVendor} onClose={() => setOpenVendor(null)} />
    </>
  );
}
