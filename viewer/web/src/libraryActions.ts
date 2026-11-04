import { Dispatch, SetStateAction } from "react";
import { api, baseName, LabelChanges, LibraryRow } from "./api";
import { ConfirmRequest, MenuEntry, systemNames } from "./menu";
import { fileEntries, renameRequest } from "./fileActions";
import { useToast } from "./toast";

/**
 * What can be done to Library rows, shared by the Library page and the Files sidebar: labels
 * (star, tags, project, users), the measurement's identity, and the file itself (open, show,
 * rename, trash). The menu is the same wherever a file is listed.
 */
export interface FileActionsContext {
  platform: string;
  login: string;
  /** the index changed because of something done here: ask for the rows again now */
  refresh: () => void;
  /** shows a confirmation or text dialog (the caller renders ConfirmDialog) */
  setConfirm: Dispatch<SetStateAction<ConfirmRequest | null>>;
  onOpenIn: (path: string, where: "explore" | "figure") => void;
  onOpenInNewBrowserTab: (path: string) => void;
  onRenamed: (oldPath: string, newPath: string) => void;
  onDeleted: (path: string) => void;
}

export function useFileActions(ctx: FileActionsContext) {
  const toast = useToast();
  const names = systemNames(ctx.platform);
  const { setConfirm, refresh } = ctx;

  /** Run a change; tell its notes (and `done`), or why it failed; then show the index's change. */
  const run = async (what: Promise<{ notes: string[] }>, done?: string) => {
    try {
      const r = await what;
      for (const n of r.notes) toast(n, "info");
      if (done) toast(done);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      refresh();
    }
  };
  const label = (paths: string[], changes: LabelChanges) => run(api.librarySetLabels(paths, changes));
  const toggleStar = (rows: LibraryRow[]) => rows.length && label(rows.map((r) => r.path), { star: !rows.every((r) => r.star) });

  const askTrash = (path: string) => {
    const name = baseName(path);
    setConfirm({
      title: `Move to the ${names.trash}?`,
      text: `Move "${name}" to the ${names.trash}? You can restore it from there.`,
      action: `Move to ${names.trash}`,
      danger: true,
      onConfirm: async () => {
        await api.trashFile(path);
        ctx.onDeleted(path);
        toast(`Moved ${name} to the ${names.trash}`);
      },
    });
  };

  const askText = (title: string, action: string, value: string, what: string, apply: (v: string) => Promise<void>) =>
    setConfirm({
      title,
      action,
      input: { value, check: (v) => (v.trim() ? null : `Type ${what}`) },
      onConfirm: (v) => apply(v.trim()),
    });

  const askNewMeasurement = (r: LibraryRow) =>
    setConfirm({
      title: "Make this a new measurement?",
      text:
        `${r.path} gets its own identity. It is written into this file only (a small change to its header); ` +
        "the other file is not touched. Its labels are kept and stop following the other file's.",
      action: "Make it a new measurement",
      onConfirm: () => run(api.libraryResolve(r.path, "new_id"), `${r.name} is now a separate measurement`),
    });

  const askGiveIds = (rows: LibraryRow[]) =>
    setConfirm({
      title: rows.length === 1 ? "Give this file an identity?" : `Give ${rows.length} files an identity?`,
      text:
        "Files written before LBD 1.3 (or by other programs) have no hidden identity, so LBD follows them by name and date. " +
        "This writes one into each file's header (its data is not changed), so their labels follow them anywhere.",
      action: "Give them an identity",
      onConfirm: () => run(api.libraryGiveIds(rows.map((x) => x.path))),
    });

  /** The menu of `rows` (several selected files), or of the one file `r`. */
  const menuEntries = (rows: LibraryRow[], r: LibraryRow): MenuEntry[] => {
    const many = rows.length > 1;
    const paths = rows.map((x) => x.path);
    const allStarred = rows.every((x) => x.star);
    const which = many ? `${rows.length} files` : r.name;
    const withoutId = rows.filter((x) => !x.id && x.read && !x.error);
    const items: MenuEntry[] = [
      { label: allStarred ? "Unstar" : "Star", onClick: () => toggleStar(rows) },
      { label: "Add tag…", onClick: () => askText(`Add a tag to ${which}`, "Add", "", "a tag", (v) => label(paths, { add_tags: [v] })) },
      { label: "Set project…", onClick: () => askText(`Project of ${which}`, "Set", rows[0].project ?? "", "a project", (v) => label(paths, { project: v })) },
      { label: "Add user…", onClick: () => askText(`Add a user to ${which}`, "Add", ctx.login, "a user", (v) => label(paths, { add_users: [v] })) },
    ];
    // the measurement's identity (copies, older files)
    const identity: MenuEntry[] = [
      ...(!many
        ? [
            { label: "Duplicate as new measurement", onClick: () => run(api.libraryDuplicate(r.path).then((d) => ({ notes: [`Copied as ${baseName(d.path)}`, ...d.notes] }))) },
            ...(r.copies || r.conflict ? [{ label: "Make this a new measurement…", onClick: () => askNewMeasurement(r) }] : []),
          ]
        : []),
      ...(withoutId.length ? [{ label: withoutId.length === 1 ? "Give this file an identity…" : `Give ${withoutId.length} files an identity…`, onClick: () => askGiveIds(withoutId) }] : []),
    ];
    if (identity.length) items.push("-", ...identity);
    if (!many)
      // one file: also what can be done with the file itself
      items.push(
        "-",
        { label: "Open in Explore", onClick: () => ctx.onOpenIn(r.path, "explore") },
        { label: "Open in Figure", onClick: () => ctx.onOpenIn(r.path, "figure") },
        "-",
        ...fileEntries(r.path, ctx.platform, toast),
        { label: "Open in new browser tab", onClick: () => ctx.onOpenInNewBrowserTab(r.path) },
        "-",
        { label: "Rename…", onClick: () => setConfirm(renameRequest(r.path, (newPath) => ctx.onRenamed(r.path, newPath), toast)) },
        { label: `Move to ${names.trash}…`, onClick: () => askTrash(r.path), danger: true },
      );
    return items;
  };

  return { run, label, toggleStar, askTrash, askText, askNewMeasurement, askGiveIds, menuEntries };
}
