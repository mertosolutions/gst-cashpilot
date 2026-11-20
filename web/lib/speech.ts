"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/* Browser speech recognition and speech synthesis (Web Speech API). Audio is handled by the browser's own speech service;
   CashPilot only ever receives the recognised text. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyRec = any;

export const LANGS = [
  { code: "en-IN", label: "English (India)" }, { code: "hi-IN", label: "हिन्दी Hindi" }, { code: "ta-IN", label: "தமிழ் Tamil" },
  { code: "te-IN", label: "తెలుగు Telugu" }, { code: "kn-IN", label: "ಕನ್ನಡ Kannada" }, { code: "ml-IN", label: "മലയാളം Malayalam" },
  { code: "mr-IN", label: "मराठी Marathi" }, { code: "bn-IN", label: "বাংলা Bengali" }, { code: "gu-IN", label: "ગુજરાતી Gujarati" },
];

function recognitionClass(): AnyRec | null {
  if (typeof window === "undefined") return null;
  const w = window as AnyRec;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access was blocked. Allow the microphone for this site in your browser settings.",
  "service-not-allowed": "Speech recognition is not allowed in this browser.",
  "no-speech": "I did not hear anything. Tap the mic and try again.",
  "audio-capture": "No microphone was found.",
  network: "The browser's speech service could not be reached. Check your internet connection.",
  "language-not-supported": "This browser does not support speech recognition for that language.",
};

export function useSpeechRecognition(lang: string, onFinal: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<AnyRec>(null);
  const finalText = useRef("");
  const cb = useRef(onFinal);
  cb.current = onFinal;

  useEffect(() => { setSupported(!!recognitionClass()); }, []);

  const start = useCallback(() => {
    const R = recognitionClass();
    if (!R) { setError("Voice input is not supported in this browser. Use Chrome or Edge, or type your question."); return; }
    try { rec.current?.abort(); } catch { /* ignore */ }
    const r = new R();
    r.lang = lang; r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
    finalText.current = ""; setInterim(""); setError(null);
    r.onstart = () => setListening(true);
    r.onresult = (e: AnyRec) => {
      let interimText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText.current += res[0].transcript; else interimText += res[0].transcript;
      }
      setInterim((finalText.current + " " + interimText).trim());
    };
    r.onerror = (e: AnyRec) => setError(ERRORS[e.error] ?? `Speech recognition error: ${e.error}`);
    r.onend = () => {
      setListening(false);
      const text = finalText.current.trim();
      if (text) cb.current(text);
    };
    rec.current = r;
    try { r.start(); } catch { setError("Could not start the microphone. Try again."); }
  }, [lang]);

  const stop = useCallback(() => { try { rec.current?.stop(); } catch { /* ignore */ } }, []);
  useEffect(() => () => { try { rec.current?.abort(); } catch { /* ignore */ } }, []);
  return { supported, listening, interim, error, start, stop, setError };
}

export function canSpeak(): boolean { return typeof window !== "undefined" && "speechSynthesis" in window; }

export function speak(text: string, lang: string, onEnd?: () => void) {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang; u.rate = 0.96;
  const voices = window.speechSynthesis.getVoices();
  const v = voices.find((x) => x.lang === lang) ?? voices.find((x) => x.lang.startsWith(lang.split("-")[0]));
  if (v) u.voice = v;
  u.onend = () => onEnd?.();
  window.speechSynthesis.speak(u);
}

export function stopSpeaking() { if (canSpeak()) window.speechSynthesis.cancel(); }
