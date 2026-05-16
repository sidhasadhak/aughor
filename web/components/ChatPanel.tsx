"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/lib/useChat";
import { ChatMessage } from "./ChatMessage";

const STARTERS = [
  "Show me the top 10 customers by revenue",
  "What is our MRR this month?",
  "Revenue by region last 30 days",
  "Which segment has the highest payment failure rate?",
];

interface Props {
  connectionId: string;
}

export function ChatPanel({ connectionId }: Props) {
  const { state, ask, clear } = useChat();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { clear(); }, [connectionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.turns.length, state.turns[state.turns.length - 1]?.status]);

  const handleSend = (q?: string) => {
    const question = (q ?? input).trim();
    if (!question || state.streaming) return;
    setInput("");
    ask(question, connectionId);
    textareaRef.current?.focus();
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {/* Conversation area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {state.turns.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-6 text-center px-6">
            <div>
              <p className="text-2xl font-semibold text-zinc-700 mb-1">Quick Chat</p>
              <p className="text-sm text-zinc-600 max-w-xs">
                Ask in plain English, get a number or chart instantly. Follow up naturally — context carries across turns.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 w-full max-w-sm">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSend(s)}
                  className="text-left text-xs text-zinc-400 hover:text-zinc-200 rounded-lg px-3 py-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 transition"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {state.turns.map((turn) => (
              <ChatMessage key={turn.id} turn={turn} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input bar */}
      <div className="border-t border-zinc-800 p-3 flex items-end gap-2 shrink-0">
        {state.turns.length > 0 && !state.streaming && (
          <button
            onClick={clear}
            title="Clear chat"
            className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors shrink-0 pb-2"
          >
            ✕
          </button>
        )}
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
          }}
          disabled={state.streaming}
          placeholder={state.turns.length > 0 ? "Follow up…" : "Ask anything…"}
          className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 placeholder:text-zinc-600 px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-500 transition disabled:opacity-50"
        />
        <button
          onClick={() => handleSend()}
          disabled={!input.trim() || state.streaming}
          className="shrink-0 rounded-lg bg-zinc-100 text-zinc-900 text-sm font-medium px-4 py-2 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {state.streaming ? (
            <span className="flex gap-0.5">
              {[0, 100, 200].map((d) => (
                <span key={d} className="w-1 h-1 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
          ) : "→"}
        </button>
      </div>
    </div>
  );
}
