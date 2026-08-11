import { useRef, useState } from "react";

type BrowserSpeechRecognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void;
};
type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

/** Thin wrapper over the browser's Web Speech API for voice-assisted intake
 * and chat input — supplementary to touch, never required (accessibility). */
export function useSpeech(lang = "en-US") {
  const [listening, setListening] = useState(false);
  const [supported] = useState(() => {
    const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
    return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
  });
  const recRef = useRef<BrowserSpeechRecognition | null>(null);

  const listen = (onResult: (text: string) => void) => {
    const w = window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor };
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = lang; rec.continuous = false; rec.interimResults = false;
    rec.onresult = (e) => {
      const text = e.results[e.results.length - 1]?.[0]?.transcript ?? "";
      if (text) onResult(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const stop = () => { recRef.current?.stop(); setListening(false); };

  return { supported, listening, listen, stop };
}
