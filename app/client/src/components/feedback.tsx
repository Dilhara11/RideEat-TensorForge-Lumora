// App-wide feedback: toast messages and a promise-based confirm dialog for destructive actions.

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";
import { Button } from "./ui";

interface ConfirmOptions {
  title: string;
  body: string;
  okLabel: string;
}

interface Feedback {
  toast: (message: string) => void;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
}

const FeedbackContext = createContext<Feedback | null>(null);

export function useFeedback(): Feedback {
  const ctx = useContext(FeedbackContext);
  if (!ctx) throw new Error("useFeedback must be used inside <FeedbackProvider>");
  return ctx;
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{ text: string; n: number } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const [pending, setPending] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  const toast = useCallback((m: string) => {
    setMessage((prev) => ({ text: m, n: (prev?.n ?? 0) + 1 }));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), 3500);
  }, []);

  const confirm = useCallback((opts: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ ...opts, resolve })), []);

  useEffect(() => {
    if (pending && !dialog.current?.open) dialog.current?.showModal();
  }, [pending]);

  const close = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
    dialog.current?.close();
  };

  return (
    <FeedbackContext.Provider value={{ toast, confirm }}>
      {children}
      <dialog
        ref={dialog}
        aria-labelledby="confirm-title"
        onCancel={(e) => {
          e.preventDefault();
          close(false);
        }}
        className="m-auto w-[min(460px,calc(100vw-32px))] rounded-card border border-border bg-surface p-6 text-text shadow-pop"
      >
        {pending && (
          <>
            <div className="flex gap-4">
              <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-full bg-danger-soft text-danger">
                <Icon name="alert" size={20} />
              </span>
              <div>
                <h2 id="confirm-title" className="mb-1.5 text-lg font-semibold">{pending.title}</h2>
                <p className="text-sm text-muted">{pending.body}</p>
              </div>
            </div>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button onClick={() => close(false)} autoFocus>Cancel</Button>
              <Button variant="danger" onClick={() => close(true)}>{pending.okLabel}</Button>
            </div>
          </>
        )}
      </dialog>
      <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-5 z-50 flex justify-center px-4">
        {message && (
          <div key={message.n} className="flex max-w-full animate-fade-up items-center gap-2.5 rounded-xl bg-nav-bg px-4 py-2.5 text-sm text-nav-text shadow-pop ring-1 ring-white/10">
            <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-brand-2" />
            {message.text}
          </div>
        )}
      </div>
    </FeedbackContext.Provider>
  );
}
