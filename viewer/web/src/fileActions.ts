// File actions shared by the Folders panel and the tab menu: show in the file manager, copy the
// path, rename. Both menus offer them, with the same words and the same checks.

import { api, baseName } from "./api";
import { ConfirmRequest, MenuEntry, systemNames } from "./menu";

type Toast = (message: string, kind?: "info" | "warning" | "error") => void;

/** The part of a name that rename keeps (same rule as the server): ".lbd.json", else the last suffix. */
export function extension(name: string): string {
  if (name.toLowerCase().endsWith(".lbd.json")) return name.slice(-".lbd.json".length);
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i) : "";
}

/** Put text on the clipboard. The clipboard API first; if the browser blocks it, the older copy command. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.style.position = "fixed";
    box.style.opacity = "0";
    document.body.appendChild(box);
    box.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      box.remove();
    }
  }
}

/** Why a new file name can't be used, or null. The server checks the same, plus existing names. */
export function checkNewName(oldName: string, name: string): string | null {
  const ext = extension(oldName);
  const n = name.trim();
  if (!n) return "Enter a file name.";
  if (n.includes("/") || n.includes("\\")) return "A file name can't contain / or \\.";
  if (extension(n).toLowerCase() !== ext.toLowerCase() || n.length <= ext.length)
    return `The name must end in ${ext}, so the file type stays the same.`;
  return null;
}

export async function copyPath(path: string, toast: Toast): Promise<void> {
  if (await copyText(path)) toast(`Copied: ${path}`);
  else toast(`Couldn't use the clipboard here. The path is: ${path}`, "error");
}

/** The "Rename file" dialog; `done` gets the new path once the file is renamed. */
export function renameRequest(path: string, done: (newPath: string) => void, toast: Toast): ConfirmRequest {
  const name = baseName(path);
  return {
    title: "Rename file",
    action: "Rename",
    input: { value: name, selectEnd: name.length - extension(name).length, check: (v) => checkNewName(name, v) },
    onConfirm: async (value) => {
      const r = await api.renameFile(path, value.trim());
      done(r.path);
      toast(`Renamed to ${baseName(r.path)}`);
    },
  };
}

/** Menu entries for one file: Show in Explorer / Finder, Copy path, and Rename… when `rename` is given. */
export function fileEntries(path: string, platform: string, toast: Toast, rename?: () => void): MenuEntry[] {
  const entries: MenuEntry[] = [
    { label: `Show in ${systemNames(platform).fileManager}`, onClick: () => api.reveal(path).catch((e) => toast((e as Error).message, "error")) },
    { label: "Copy path", onClick: () => copyPath(path, toast) },
  ];
  if (rename) entries.push({ label: "Rename…", onClick: rename });
  return entries;
}
