import { createContext, ReactNode, useCallback, useContext, useState } from "react";

type Kind = "info" | "warning" | "error";
interface Toast {
  id: number;
  text: string;
  kind: Kind;
}

const ToastContext = createContext<(text: string, kind?: Kind) => void>(() => undefined);

export function useToast() {
  return useContext(ToastContext);
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((text: string, kind: Kind = "info") => {
    const id = nextId++;
    setToasts((t) => [...t, { id, text, kind }]);
    // How long a message stays: warnings and errors longer, so they can be read.
    const ms = { info: 3500, warning: 10000, error: 8000 }[kind];
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ms);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span>{t.text}</span>
            <button className="toast-close" aria-label="Close" title="Close"
                    onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
