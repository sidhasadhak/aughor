// @vitest-environment jsdom
/**
 * A `?chat=` link opened an empty conversation, on every reload (2026-10-02): the canvas mounts the chat
 * panel before its connection has loaded, the restore wrote the turns into that Chat, and the arriving
 * connection rebuilt the Chat — same id, no turns. The connection now rides a ref; only a new session id
 * makes a new Chat.
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAughorChat } from "@/lib/useAughorChat";

const turn = { id: "m1", role: "user" as const, parts: [{ type: "text" as const, text: "What was total revenue in July 2026?" }] };

describe("a restored conversation", () => {
  it("survives its connection arriving after it", () => {
    const { result, rerender } = renderHook((p: { connectionId: string; sessionId: string }) => useAughorChat(p),
                                            { initialProps: { connectionId: "", sessionId: "s1" } });
    act(() => result.current.setMessages([turn]));
    rerender({ connectionId: "8233e4fd", sessionId: "s1" });
    expect(result.current.messages.map((m) => m.id)).toEqual(["m1"]);
  });

  it("a new session is a new, empty conversation", () => {
    const { result, rerender } = renderHook((p: { connectionId: string; sessionId: string }) => useAughorChat(p),
                                            { initialProps: { connectionId: "c", sessionId: "s1" } });
    act(() => result.current.setMessages([turn]));
    rerender({ connectionId: "c", sessionId: "s2" });
    expect(result.current.messages).toEqual([]);
  });
});
