"use client";

/**
 * The AI SDK chat hook, bound to Aughor's stream — CI-1d, promoted in CA-1.
 *
 * This is the client half of the seam whose server half is `app/api/chat/route.ts`.
 * `DefaultChatTransport` already defaults its `api` to `/api/chat`, so the two ends
 * meet without configuration — but it is named explicitly here because a default
 * that silently moves is how a working path stops working.
 *
 * CA-1: this is now THE chat hook. `lib/useChat.ts` (the 107-case reducer and its
 * hand-rolled lifecycle) is retired; every chat surface — the workspace panel, the
 * full-page `/chat`, the briefing's ask panel and inline threads — drives this hook
 * and renders through `projectTurn` (`lib/chatTurn.ts`). Per-turn options (depth,
 * schema, seeds, resume approvals) ride each `sendMessage`'s `body`, which the
 * route handler maps onto the same backend endpoints the reducer path called.
 *
 * WHY A `Chat` INSTANCE RATHER THAN OPTIONS. `useChat` in this version is thin —
 * it takes an already-constructed `Chat` and subscribes to it. Constructing that
 * instance inside the component body would build a NEW chat on every render and
 * throw the conversation away, so it is memoised on the fields that actually
 * identify a conversation.
 */

import { useEffect, useMemo, useRef } from "react";

import { Chat, useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { DataUIPart } from "ai";

import type { AughorUIDataTypes } from "./aughorUIDataTypes";
import type { AughorUIMessage } from "./chatTurn";

export type { AughorUIMessage };

export interface UseAughorChatOptions {
  /** The connection every turn in this conversation runs against. */
  connectionId: string;
  /**
   * Stable id for the conversation. Also the SESSION the backend reconstructs
   * history from when the client sends none (`resolve_history` — CI-1), which is
   * what makes a reload or a second device non-memoryless. Changing it starts a
   * different conversation, so it must not be regenerated per render.
   */
  sessionId: string;
  /** Merged into every request's body (e.g. a canvas id or schema scope the
   *  whole conversation is pinned to). Per-turn overrides ride `sendMessage`. */
  body?: Record<string, unknown>;
  onError?: (e: Error) => void;
  /** Every data part, as it arrives — the debug log's feed. */
  onData?: (part: DataUIPart<AughorUIDataTypes>) => void;
}

export function useAughorChat({
  connectionId,
  sessionId,
  body,
  onError,
  onData,
}: UseAughorChatOptions) {
  // Callbacks ride refs so a re-rendered parent handing a fresh closure does not
  // rebuild the Chat and throw the conversation away. Mirrored in an effect —
  // the refs are only ever read at request/stream time, never during render.
  const onErrorRef = useRef(onError);
  const onDataRef = useRef(onData);
  const bodyRef = useRef(body);
  useEffect(() => {
    onErrorRef.current = onError;
    onDataRef.current = onData;
    bodyRef.current = body;
  });

  const chat = useMemo(
    () =>
      new Chat<AughorUIMessage>({
        id: sessionId,
        transport: new DefaultChatTransport<AughorUIMessage>({
          api: "/api/chat",
          // Sent alongside `messages` on every turn. `session_id` is what lets the
          // server rebuild the thread from its own store rather than trusting the
          // client to be the only memory. Resolved per request, so a late-arriving
          // canvas/schema pin applies without rebuilding the conversation.
          body: () => ({
            connection_id: connectionId,
            session_id: sessionId,
            ...(bodyRef.current ?? {}),
          }),
        }),
        onError: (e) => onErrorRef.current?.(e),
        onData: (part) => onDataRef.current?.(part),
      }),
    [connectionId, sessionId],
  );

  return useChat({ chat });
}
