"use client";

/**
 * "Make a cockpit" on an object's panel in the Ontology tab (2026-10-10): the starter in a dialog, and the new cockpit
 * opened in the Cockpit tab once it is kept. Offered while a cockpit may start from an object here
 * (`ontology.dashboard_pieces` and `ontology.object_dashboards`); absent otherwise, never a button that refuses.
 */
import { useEffect, useState } from "react";

import { ObjectDashboardStarter } from "@/components/dashboards/ObjectDashboardStarter";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { getSystemFlags } from "@/lib/api";
import { requestTab } from "@/lib/navigate";
import { effectiveCurrencySymbol } from "@/lib/orgSettings";

export function MakeDashboard({ connectionId, schema, entity, name }: {
  connectionId: string; schema?: string; entity: string; name: string;
}) {
  const [on, setOn] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    getSystemFlags()
      .then(f => { if (alive) setOn(!!f["ontology.dashboard_pieces"]?.value && !!f["ontology.object_dashboards"]?.value); })
      .catch(() => { if (alive) setOn(false); });
    return () => { alive = false; };
  }, []);
  if (!on) return null;
  return (
    <>
      <Button size="xs" variant="secondary" data-testid="make-dashboard" style={{ marginLeft: "auto" }} onClick={() => setOpen(true)}>
        <Icon name="canvas" size={12} /> Make a dashboard
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent maxWidth="760px">
          <DialogTitle className="sr-only">New dashboard from {name}</DialogTitle>
          {open && (
            <ObjectDashboardStarter connectionId={connectionId} schema={schema} entity={entity} sym={effectiveCurrencySymbol() || "$"}
              onCancel={() => setOpen(false)}
              onKept={() => { setOpen(false); requestTab("dashboards", { conn: connectionId }); }} />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
