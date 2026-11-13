// Settings that change a lot ask first (plan 18, 18.7): one that writes data files differently,
// deletes something, or costs a lot (download, disk, time). The question says what will happen, in
// numbers, and nothing changes until the user agrees. Everything else takes effect at once.
// The Settings dialog provides `askFirst`; the parts of it in other files (previews, memory) use it.

import { createContext, useContext } from "react";
import type { ConfirmRequest } from "./menu";
import type { DataFileEdits } from "./api";

export const AskFirst = createContext<(request: ConfirmRequest) => void>((request) => void request.onConfirm("", []));

export const useAskFirst = () => useContext(AskFirst);

/** What each way of editing a finished data file means (also asked at the first start, 18.8). */
export const EDIT_TEXTS: Record<DataFileEdits, { name: string; text: string }> = {
  in_place: {
    name: "In place",
    text:
      "LBD changes only what changes, inside the file: about 10 ms at any size, and a sync tool sends only " +
      "a little. But a write cut half-way (a power cut, a dropped network) can damage the file.",
  },
  copy_and_swap: {
    name: "Copy and swap",
    text:
      "LBD writes a complete copy of the file and puts it in the file's place: even a power cut can't damage " +
      "the file. It needs room for the copy, takes about 1 s per GB, and a sync tool sends the whole file each time.",
  },
};
