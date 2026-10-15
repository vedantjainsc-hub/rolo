import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { cx } from "./ui";

type Tone = "info" | "success" | "error";
export type ToastAction = { label: string; onClick: () => void };
type Toast = { id: number; text: string; tone: Tone; action?: ToastAction };
type Show = (text: string, tone?: Tone, opts?: { action?: ToastAction }) => void;

const Ctx = createContext<Show>(() => {});

export function useToast() {
  return useContext(Ctx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const show = useCallback<Show>(
    (text, tone = "info", opts) => {
      const id = next.current++;
      setToasts((t) => [...t.slice(-2), { id, text, tone, action: opts?.action }]);
      // Toasts with an action (Undo) stay longer so there is time to tap it.
      setTimeout(() => dismiss(id), opts?.action ? 7000 : 3500);
    },
    [dismiss],
  );
  return (
    <Ctx.Provider value={show}>
      {children}
      <div
        aria-live="polite"
        role="status"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(96px+env(safe-area-inset-bottom))] z-50 flex flex-col items-center gap-2 px-5"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "on-navy pointer-events-auto flex max-w-[600px] items-center gap-3 rounded-[12px] py-1 pl-4 text-body text-white shadow-card",
              t.action ? "pr-1" : "pr-4 py-3",
              t.tone === "error" ? "bg-danger" : t.tone === "success" ? "bg-success" : "bg-navy-900",
            )}
          >
            <span className={t.action ? "py-2" : ""}>{t.text}</span>
            {t.action && (
              <button
                type="button"
                onClick={() => {
                  dismiss(t.id);
                  t.action?.onClick();
                }}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[10px] px-3 font-semibold underline underline-offset-4 hover:bg-white/10"
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
