import { useCallback, useState } from "react";
import { HISTORY_LIMIT } from "./editorConfig";
import type { EditorDocument } from "./types";

type HistoryState = {
  past: EditorDocument[];
  present: EditorDocument;
  future: EditorDocument[];
};

export function useEditorHistory(initialDocument: EditorDocument) {
  const [history, setHistory] = useState<HistoryState>({
    past: [],
    present: initialDocument,
    future: [],
  });

  const commit = useCallback((update: (current: EditorDocument) => EditorDocument) => {
    setHistory((current) => {
      const nextDocument = update(current.present);
      if (nextDocument === current.present) return current;
      return {
        past: [...current.past, current.present].slice(-HISTORY_LIMIT),
        present: nextDocument,
        future: [],
      };
    });
  }, []);

  const undo = useCallback(() => {
    setHistory((current) => {
      const previous = current.past.at(-1);
      if (!previous) return current;
      return {
        past: current.past.slice(0, -1),
        present: previous,
        future: [current.present, ...current.future],
      };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((current) => {
      const next = current.future[0];
      if (!next) return current;
      return {
        past: [...current.past, current.present],
        present: next,
        future: current.future.slice(1),
      };
    });
  }, []);

  return {
    document: history.present,
    commit,
    undo,
    redo,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  };
}
