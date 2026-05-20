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
      <div className="flex-1 overflow-y-auto min-h-0">
        {state.turns.length === 0 ? (
          /* Empty state — centered hero */
          <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
            <p className="text-2xl font-semibold text-zinc-700">Ask your data anything</p>
            <p className="text-sm text-zinc-600 max-w-xs leading-relaxed">
              Plain English questions → instant numbers and charts.
              Context carries across turns.
            </p>
          </div>
        ) : (
          <div className="p-5 space-y-5 max-w-3xl mx-auto w-full">
            {state.turns.map((turn) => (
              <ChatMessage key={turn.id} turn={turn} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Starter chips — shown above input only when empty */}
      {state.turns.length === 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5 justify-center max-w-2xl mx-auto w-full">
          {STARTERS.map((s) => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              className="text-xs text-zinc-500 hover:text-zinc-200 rounded-full px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700/70 border border-zinc-600 hover:border-zinc-600 transition"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input bar — always at bottom */}
      <div className="border-t border-zinc-600 px-4 py-3 flex items-end gap-2 shrink-0 bg-zinc-800">
        {state.turns.length > 0 && !state.streaming && (
          <button
            onClick={clear}
            title="Clear conversation"
            className="text-xs text-zinc-700 hover:text-zinc-400 transition-colors shrink-0 pb-2"
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
          placeholder={state.turns.length > 0 ? "Follow up…" : "Ask anything about your data…"}
          className="flex-1 rounded-xl bg-zinc-800 border border-zinc-600 text-sm text-zinc-100 placeholder:text-zinc-600 px-4 py-2.5 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-600 transition disabled:opacity-50"
        />
        <button
          onClick={() => handleSend()}
          disabled={!input.trim() || state.streaming}
          className="shrink-0 rounded-xl bg-zinc-100 text-zinc-900 text-sm font-medium px-4 py-2.5 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {state.streaming ? (
            <span className="flex gap-0.5 py-0.5">
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
