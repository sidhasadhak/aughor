"use client";
/* ── VA-10 · the topbar identity control ────────────────────────────────────
   Renders from the SERVED auth config (/auth/config — public by construction):

     · OIDC not configured  → the static avatar the topbar always had
     · configured, no token → Sign in with Google (Google Identity Services;
                              the widget is provider-shaped, verification is not)
     · signed in            → initials chip; click for email + sign out

   The credential GIS hands back is Google's ID token; it goes into the fetch
   wrapper (lib/auth.ts) and the SERVER verifies it on every call — nothing
   here trusts a claim beyond painting initials. */
import { useCallback, useEffect, useRef, useState } from "react";
import { getApiBase } from "@/lib/config";
import {
  AUTH_EXPIRED_EVENT, claimsOf, clearIdToken, getIdToken, setIdToken,
} from "@/lib/auth";
import { Button } from "@/components/ui/button";

interface AuthConfig {
  oidc_configured: boolean;
  identity_required?: boolean;
  issuer?: string;
  client_id?: string;
  provider?: string;
}

declare global {
  interface Window {
    google?: {
      accounts: { id: {
        initialize: (cfg: object) => void;
        renderButton: (el: HTMLElement, cfg: object) => void;
      } };
    };
  }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

function StaticAvatar() {
  // No identity is configured, so there is no one to name — the avatar alone, in the
  // user-menu frame the signed-in state wears.
  return (
    <div className="aug-user-menu" style={{ padding: 2 }} title="No identity configured">
      <span className="aug-avatar">AU</span>
    </div>
  );
}

export function AuthControl() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const buttonHost = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setToken(getIdToken());
    fetch(`${getApiBase()}/auth/config`)
      .then(r => (r.ok ? r.json() : null))
      .then(setConfig)
      .catch(() => setConfig(null));
    const expired = () => setToken(null);
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  }, []);

  const onCredential = useCallback((resp: { credential?: string }) => {
    if (!resp?.credential) return;
    setIdToken(resp.credential);
    // Everything already on screen was fetched without the identity —
    // reload so every panel re-reads as the signed-in principal.
    window.location.reload();
  }, []);

  // Load GIS and render its button only in the signed-out, Google-configured state.
  useEffect(() => {
    if (!config?.oidc_configured || config.provider !== "google" || token) return;
    let cancelled = false;
    const render = () => {
      if (cancelled || !window.google || !buttonHost.current || !config.client_id) return;
      window.google.accounts.id.initialize({
        client_id: config.client_id, callback: onCredential,
      });
      window.google.accounts.id.renderButton(buttonHost.current, {
        type: "standard", size: "small", text: "signin", shape: "rectangular",
      });
    };
    if (window.google) render();
    else {
      let script = document.querySelector(`script[src="${GSI_SRC}"]`) as HTMLScriptElement | null;
      if (!script) {
        script = document.createElement("script");
        script.src = GSI_SRC;
        script.async = true;
        document.head.appendChild(script);
      }
      script.addEventListener("load", render);
      return () => { cancelled = true; script?.removeEventListener("load", render); };
    }
    return () => { cancelled = true; };
  }, [config, token, onCredential]);

  if (!config?.oidc_configured) return <StaticAvatar />;

  if (!token) {
    return (
      <div style={{ display: "flex", alignItems: "center" }}>
        <div ref={buttonHost} data-testid="gsi-button-host" />
        {config.provider !== "google" && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            OIDC configured — supply a bearer token
          </span>
        )}
      </div>
    );
  }

  const email = claimsOf(token)?.email ?? "signed in";
  const initials = email.slice(0, 2).toUpperCase();
  return (
    <div style={{ position: "relative" }}>
      <Button variant="ghost" onClick={() => setMenuOpen(o => !o)} title={email}
        aria-expanded={menuOpen}
        className="aug-user-menu h-auto font-normal">
        <span className="aug-avatar">{initials}</span>
        <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {email.split("@")[0]}
        </span>
        <span aria-hidden className="aug-mono" style={{ color: "var(--t3)" }}>▾</span>
      </Button>
      {menuOpen && (
        <div style={{
          position: "absolute", right: 0, top: 34, zIndex: 60, minWidth: 200,
          background: "var(--bg-3)", border: "1px solid var(--b2)",
          borderRadius: "var(--r2)", boxShadow: "var(--shadow-sm)", padding: 10,
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <span className="aug-fs-sm" style={{ color: "var(--t1)", overflowWrap: "anywhere" }}>{email}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>verified by the server on every call</span>
          <Button variant="ghost" size="xs" className="h-auto px-2 py-1 aug-fs-xs font-normal"
            style={{ border: "1px solid var(--b1)", alignSelf: "flex-start" }}
            onClick={() => { clearIdToken(); setToken(null); setMenuOpen(false); window.location.reload(); }}>
            Sign out
          </Button>
        </div>
      )}
    </div>
  );
}
