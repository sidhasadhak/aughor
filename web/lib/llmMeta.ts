/** Display names for the LLM providers (backends) the platform can bind.
 *
 *  Shared by the Models tab (Settings → Models, the one place a model is chosen)
 *  and every surface that only *names* the provider — so "openrouter" reads the
 *  same everywhere without each panel keeping its own copy of this map.
 */
export const BACKEND_LABEL: Record<string, string> = {
  ollama: "Ollama (local)",
  lmstudio: "LM Studio (local)",
  groq: "Groq",
  together: "Together AI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  openrouter: "OpenRouter",
};
