// Modal routing replay for one row of a results table. Opens when `item` is set; plays straight away.

import { useEffect, useRef } from "react";
import { Icon } from "../../components/icons";
import { Button } from "../../components/ui";
import type { ResultItem } from "../../lib/types";
import { RoutingSimulator } from "./RoutingSimulator";

export function RouteDialog({ item, onClose }: { item: ResultItem | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (item && !dialog.current?.open) dialog.current?.showModal();
    if (!item && dialog.current?.open) dialog.current.close();
  }, [item]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="route-dialog-title"
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && dialog.current?.close()}
      className="m-auto max-h-[calc(100vh-32px)] w-[min(1080px,calc(100vw-32px))] overflow-y-auto rounded-card border border-border bg-surface p-0 text-text shadow-pop"
    >
      {item && (
        <div className="p-5 sm:p-6">
          <div className="mb-5 flex items-start gap-3">
            <span aria-hidden="true" className="grid size-10 place-items-center rounded-lg bg-brand text-white">
              <Icon name="route" size={19} />
            </span>
            <div className="mr-auto">
              <h2 id="route-dialog-title" className="text-lg font-semibold leading-tight">Routing simulation</h2>
              <p className="text-sm text-muted">A replay of how this ticket moves through triage, built from its prediction.</p>
            </div>
            <Button variant="ghost" size="icon" aria-label="Close" onClick={() => dialog.current?.close()}>
              <Icon name="x" size={18} />
            </Button>
          </div>
          {/* key: a fresh replay for every row opened */}
          <RoutingSimulator key={`${item.prediction.ticket_id ?? ""}-${item.row ?? ""}`} prediction={item.prediction} ticket={item.ticket} autoPlay />
        </div>
      )}
    </dialog>
  );
}
