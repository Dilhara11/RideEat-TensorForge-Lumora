// API-key dialog. Opens from the header button, or automatically when a protected call gets a 401.
// The key is verified against the server before it is saved.

import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState, type FormEvent } from "react";
import { ApiError, apiKey, unauthorizedEvents, verifyKey } from "../lib/api";
import { Icon } from "./icons";
import { Button, FieldError } from "./ui";

export interface KeyDialogHandle {
  open: (reason?: string) => void;
}

export const KeyDialog = forwardRef<KeyDialogHandle>(function KeyDialog(_, ref) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const errorId = useId();

  const open = (reason?: string) => {
    if (dialog.current?.open) return;
    setValue(apiKey.get() ?? "");
    setRemember(apiKey.isRemembered());
    setHasKey(Boolean(apiKey.get()));
    setError(reason ?? null);
    setReveal(false);
    dialog.current?.showModal();
    window.setTimeout(() => input.current?.focus(), 0);
  };

  useImperativeHandle(ref, () => ({ open }));

  useEffect(() => {
    const onUnauthorized = () =>
      open(apiKey.get() ? "The server rejected the saved key. Enter the current key." : "Enter the API key to classify tickets.");
    unauthorizedEvents.addEventListener("unauthorized", onUnauthorized);
    return () => unauthorizedEvents.removeEventListener("unauthorized", onUnauthorized);
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const key = value.trim();
    if (!key) return setError("Enter the API key.");
    setChecking(true);
    try {
      if (!(await verifyKey(key))) return setError("This key was rejected by the server. Check it and try again.");
      dialog.current?.close();
      apiKey.set(key, remember);
    } catch (ex) {
      setError(ex instanceof ApiError && ex.status === 0 ? "Can't reach the server to check the key." : "Couldn't check the key.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <dialog
      ref={dialog}
      aria-labelledby="key-dialog-title"
      className="m-auto w-[min(460px,calc(100vw-32px))] rounded-card border border-border bg-surface p-6 text-text shadow-pop"
    >
      <form onSubmit={submit} noValidate>
        <span aria-hidden="true" className="mb-4 grid size-11 place-items-center rounded-xl bg-accent-soft text-accent">
          <Icon name="key" size={20} />
        </span>
        <h2 id="key-dialog-title" className="mb-1.5 text-lg font-semibold">Connect with your API key</h2>
        <p className="mb-5 text-sm text-muted">Classifying tickets needs the service API key. It stays in this browser and is only sent to this server.</p>
        <label htmlFor="key-input" className="mb-1.5 block text-sm font-semibold">API key</label>
        <div className="flex gap-2">
          <input
            id="key-input"
            ref={input}
            type={reveal ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            className="control min-w-0 flex-1"
          />
          <Button aria-pressed={reveal} onClick={() => setReveal((r) => !r)}>{reveal ? "Hide" : "Show"}</Button>
        </div>
        <FieldError id={errorId}>{error}</FieldError>
        <label className="mt-4 flex min-h-8 cursor-pointer items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="size-4.5 accent-accent" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember on this device
        </label>
        <p className="mt-1 text-[13px] text-muted">If you don't tick this, the key is forgotten when you close the tab.</p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          {hasKey && (
            <Button
              variant="danger-ghost"
              onClick={() => {
                apiKey.clear();
                dialog.current?.close();
              }}
            >
              Forget key
            </Button>
          )}
          <span className="flex-1" />
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
          <Button type="submit" variant="primary" busy={checking} busyLabel="Checking…">Save key</Button>
        </div>
      </form>
    </dialog>
  );
});
