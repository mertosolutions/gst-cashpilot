"use client";
import { createContext, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { setAuthProvider } from "./api";

const FIREBASE_ON = !!process.env.NEXT_PUBLIC_FIREBASE_API_KEY;
export const DEMO_USERS = [
  { uid: "demo-owner", label: "Demo Traders (has data)" },
  { uid: "other-business", label: "Another business (empty)" },
];

interface AuthState { ready: boolean; mode: "demo" | "firebase"; uid: string | null; name: string | null; signIn: () => Promise<void>; signOut: () => Promise<void>; switchDemo: (uid: string) => void }
const Ctx = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [uid, setUid] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    if (!FIREBASE_ON) {
      const saved = (typeof window !== "undefined" && localStorage.getItem("cashpilot.demoUser")) || DEMO_USERS[0].uid;
      setUid(saved);
      setName(DEMO_USERS.find((u) => u.uid === saved)?.label ?? saved);
      setAuthProvider(async () => ({ "X-Demo-User": localStorage.getItem("cashpilot.demoUser") || DEMO_USERS[0].uid }));
      setReady(true);
      return;
    }
    let unsub = () => {};
    (async () => {
      const { getFirebaseAuth } = await import("./firebase");
      const { onAuthStateChanged } = await import("firebase/auth");
      const auth = getFirebaseAuth();
      setAuthProvider(async (): Promise<Record<string, string>> => {
        const t = await auth.currentUser?.getIdToken();
        return t ? { Authorization: `Bearer ${t}` } : {};
      });
      unsub = onAuthStateChanged(auth, (u) => { setUid(u?.uid ?? null); setName(u?.displayName ?? u?.email ?? null); setReady(true); });
    })();
    return () => unsub();
  }, []);

  const value = useMemo<AuthState>(() => ({
    ready, mode: FIREBASE_ON ? "firebase" : "demo", uid, name,
    signIn: async () => {
      const { getFirebaseAuth } = await import("./firebase");
      const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
      await signInWithPopup(getFirebaseAuth(), new GoogleAuthProvider());
    },
    signOut: async () => {
      const { getFirebaseAuth } = await import("./firebase");
      const { signOut } = await import("firebase/auth");
      await signOut(getFirebaseAuth());
    },
    switchDemo: (u: string) => { localStorage.setItem("cashpilot.demoUser", u); window.location.reload(); },
  }), [ready, uid, name]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
