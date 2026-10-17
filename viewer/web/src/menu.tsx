import { FormEvent, KeyboardEvent, MouseEvent, useEffect, useLayoutEffect, useRef, useState } from "react";

/** One entry of a right-click menu; "-" is a separator line. */
export type MenuEntry = { label: string; onClick: () => void; danger?: boolean } | "-";

export interface MenuAt {
  x: number;
  y: number;
  items: MenuEntry[];
}

/** Where to open a menu: at the mouse, or (keyboard: Menu key, Shift+F10) under the focused row. */
export function menuAt(e: MouseEvent | KeyboardEvent, items: MenuEntry[]): MenuAt {
  if ("clientX" in e && e.type === "contextmenu" && (e.clientX || e.clientY)) return { x: e.clientX, y: e.clientY, items };
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  return { x: r.left + 24, y: r.bottom, items };
}

/** True for the keys that open a context menu from the keyboard. */
export function isMenuKey(e: KeyboardEvent): boolean {
  return e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey);
}

/** A right-click menu. Closes on a choice, Escape, a click or mouse-wheel scroll elsewhere, or resizing. */
export function ContextMenu({ menu, onClose }: { menu: MenuAt; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: menu.x, top: menu.y });

  // Keep the menu inside the window, and put the focus on its first item.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setPos({
      left: Math.max(4, Math.min(menu.x, window.innerWidth - width - 4)),
      top: Math.max(4, Math.min(menu.y, window.innerHeight - height - 4)),
    });
    el.querySelector("button")?.focus();
  }, [menu]);

  useEffect(() => {
    const away = (e: Event) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const close = () => onClose();
    document.addEventListener("mousedown", away, true);
    document.addEventListener("wheel", away, true); // scrolling by the user; layout scrolls are ignored
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("mousedown", away, true);
      document.removeEventListener("wheel", away, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
    };
  }, [onClose]);

  const onKeyDown = (e: KeyboardEvent) => {
    const buttons = [...(ref.current?.querySelectorAll("button") ?? [])];
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") buttons[(i + 1) % buttons.length]?.focus();
    else if (e.key === "ArrowUp") buttons[(i - 1 + buttons.length) % buttons.length]?.focus();
    else if (e.key === "Tab") onClose();
    else return;
    e.preventDefault();
  };

  return (
    <div ref={ref} className="context-menu" role="menu" style={pos} onKeyDown={onKeyDown} onContextMenu={(e) => e.preventDefault()}>
      {menu.items.map((item, i) =>
        item === "-" ? (
          <div key={i} className="menu-separator" role="separator" />
        ) : (
          <button
            key={i}
            role="menuitem"
            className={item.danger ? "danger" : ""}
            onClick={() => {
              onClose();
              item.onClick();
            }}
          >
            {item.label}
          </button>
        ),
      )}
    </div>
  );
}

export interface ConfirmRequest {
  title: string;
  text?: string;
  /** The button that applies the change, e.g. "Rename". */
  action: string;
  danger?: boolean;
  /** A text box, e.g. for the new name: its first value, the part to select, and a check. */
  input?: { value: string; selectEnd?: number; check: (value: string) => string | null };
  /** Do the change. If it throws, the message is shown in the dialog and it stays open. */
  onConfirm: (value: string) => Promise<void> | void;
  /** An optional third choice next to Cancel, e.g. "Reload" beside "Overwrite". */
  secondary?: { label: string; onClick: () => Promise<void> | void };
}

/** A modal dialog that asks before a change is applied. Cancel is the default button. */
export function ConfirmDialog({ request, onClose }: { request: ConfirmRequest; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(request.input?.value ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const problem = request.input ? request.input.check(value) : null;

  useEffect(() => {
    ref.current?.showModal();
    const input = inputRef.current;
    if (input) {
      input.focus();
      input.setSelectionRange(0, request.input?.selectEnd ?? input.value.length);
    }
  }, [request]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (problem || busy) return;
    setBusy(true);
    try {
      await request.onConfirm(value);
      onClose();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <dialog ref={ref} className="confirm-dialog" onCancel={onClose} aria-labelledby="confirm-title">
      <form onSubmit={submit}>
        <h3 id="confirm-title">{request.title}</h3>
        {request.text && <p>{request.text}</p>}
        {request.input && (
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            aria-label={request.title}
            aria-invalid={!!problem}
          />
        )}
        {(problem || error) && <p className="dialog-error">{error ?? problem}</p>}
        <div className="dialog-buttons">
          {/* Without a text box, Cancel has the focus, so pressing Enter changes nothing. */}
          <button type="button" onClick={onClose} autoFocus={!request.input}>
            Cancel
          </button>
          {request.secondary && (
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                await request.secondary!.onClick();
                onClose();
              }}
            >
              {request.secondary.label}
            </button>
          )}
          <button type="submit" className={request.danger ? "danger" : "primary"} disabled={!!problem || busy}>
            {request.action}
          </button>
        </div>
      </form>
    </dialog>
  );
}

/** The name of the system's file manager and trash, for menu labels. */
export function systemNames(platform: string): { fileManager: string; trash: string } {
  if (platform === "win32") return { fileManager: "Explorer", trash: "Recycle Bin" };
  if (platform === "darwin") return { fileManager: "Finder", trash: "Trash" };
  return { fileManager: "file manager", trash: "Trash" };
}
