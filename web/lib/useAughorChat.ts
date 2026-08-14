"use client";

/**
 * The AI SDK chat hook, bound to Aughor's stream — CI-1d.
 *
 * This is the client half of the seam whose server half is `app/api/chat/route.ts`.
 * `DefaultChatTransport` already defaults its `api` to `/api/chat`, so the two ends
 * meet without configuration — but it is named explicitly here because a default
 * that silently moves is how a working path stops working.
 *
 * WHAT THIS IS NOT. It does not replace `lib/useChat.ts`. That hook owns the
 * 107-case reducer, the `ChatTurn` shape, and the lifecycle five components depend
 * on; swapping it wholesale is the high-regression half of CI-1d and wants its own
 * change. The two coexist deliberately: this one proves the parts model end to end
 * against a real backend, and the migration then moves surfaces across one at a
 * time with something already known to work underneath.
 *
 * WHY A `Chat` INSTANCE RATHER THAN OPTIONS. `useChat` in this version is thin —
 * it takes an already-constructed `Chat` and subscribes to it. Constructing that
 * instance inside the component body would build a NEW chat on every render and
 * throw the conversation away, so it is memoised on the fields that actually
 * identify a conversation.
 */

import { useMemo } from "react";

import { Chat, useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { UIMessage } from "ai";

import type { AughorUIDataTypes } from "./aughorUIDataTypes";

/** A message whose data parts are Aughor's declared vocabulary. */
export type AughorUIMessage = UIMessage<unknown, AughorUIDataTypes>;

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
  onError?: (e: Error) => void;
}

export function useAughorChat({ connectionId, sessionId, onError }: UseAughorChatOptions) {
  const chat = useMemo(
    () =>
      new Chat<AughorUIMessage>({
        id: sessionId,
        transport: new DefaultChatTransport<AughorUIMessage>({
          api: "/api/chat",
          // Sent alongside `messages` on every turn. `session_id` is what lets the
          // server rebuild the thread from its own store rather than trusting the
          // client to be the only memory.
          body: { connection_id: connectionId, session_id: sessionId },
        }),
        onError,
      }),
    [connectionId, sessionId, onError],
  );

  return useChat({ chat });
}
