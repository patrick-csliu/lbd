import { createContext, ReactNode, useCallback, useContext, useState } from "react";

type Kind = "info" | "warning" | "error";
/** A button in the toast, e.g. "Undo"; the toast closes when it is clicked. */
export interface ToastAction {
  label: string;
  onClick: () => void;
}
interface Toast {
  id: number;
  text: string;
  kind: Kind;
  action?: ToastAction;
}

const ToastContext = createContext<(text: string, kind?: Kind, action?: ToastAction) => void>(() => undefined);

export function useToast() {
  return useContext(ToastContext);
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((text: string, kind: Kind = "info", action?: ToastAction) => {
    const id = nextId++;
    setToasts((t) => [...t, { id, text, kind, action }]);
    // How long a message stays: warnings and errors longer, so they can be read; one with a
    // button (Undo) long enough to use it.
    const ms = action ? 8000 : { info: 3500, warning: 10000, error: 8000 }[kind];
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ms);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span>{t.text}</span>
            {t.action && (
              <button
                className="toast-action"
                onClick={() => {
                  t.action!.onClick();
                  setToasts((x) => x.filter((y) => y.id !== t.id));
                }}
              >
                {t.action.label}
              </button>
            )}
            <button className="toast-close" aria-label="Close" title="Close"
                    onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
