import { LibraryColumn } from "./api";

/** Sort by name or date: the chosen one is lit, a click on it again reverses the order. `nameBy`:
 * what Name sorts by (the title, or the file name when the list shows that). */
export function SortButtons({ sort, order, nameBy = "name", onSort }: { sort?: string; order?: string; nameBy?: LibraryColumn; onSort: (c: LibraryColumn) => void }) {
  const button = (c: LibraryColumn, text: string, tip: string) => {
    const on = sort === c;
    return (
      <button className={on ? "on" : ""} aria-pressed={on} title={on ? `${tip}; click again to reverse` : tip} onClick={() => onSort(c)}>
        {text}
        {on ? (order === "asc" ? " ▴" : " ▾") : ""}
      </button>
    );
  };
  return (
    <span className="sort-buttons" role="group" aria-label="Sort the files by">
      {button(nameBy, "Name", "Sort by name")}
      {button("date", "Date", "Sort by date")}
    </span>
  );
}
