import { useState, useRef, useCallback } from 'react';

const SpeechRecognition = typeof window !== 'undefined'
  ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

/** Mic button: dictates one question. Not rendered where the browser has no
 *  speech recognition (Firefox), instead of a button that can only apologise. */
export default function VoiceInput({ onTranscript, disabled, lang = 'en', title }) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);

  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = lang === 'ar' ? 'ar-SA' : 'en-US';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      if (onTranscript) onTranscript(transcript);
      setIsListening(false);
    };

    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [isListening, onTranscript, lang]);

  if (!SpeechRecognition) return null;

  return (
    <button
      onClick={toggleListening}
      disabled={disabled}
      title={title || "Speak instead of typing"}
      className={`relative w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all ${
        isListening
          ? 'bg-red-500/15 text-red-500'
          : 'hover:bg-[rgba(0,114,206,0.08)]'
      } disabled:opacity-30`}
      style={!isListening ? { color: 'var(--text-dim)' } : {}}
    >
      {isListening && (
        <span className="absolute inset-0 rounded-lg border-2 border-red-400/40 animate-ping" />
      )}
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
        <line x1="12" y1="19" x2="12" y2="23"/>
        <line x1="8" y1="23" x2="16" y2="23"/>
      </svg>
    </button>
  );
}
