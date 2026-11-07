import { useEffect, useState } from "react";

export type CreationPanel = "form" | "results";

// Match the CSS breakpoint so resizing never changes or discards form state.
export const MOBILE_LAYOUT_QUERY =
  "(max-width: 767px), (hover: none) and (pointer: coarse) and (max-width: 1023px)";

export function useCreationPanel() {
  const [panel, setPanel] = useState<CreationPanel>("form");
  useEffect(() => {
    if (window.matchMedia?.(MOBILE_LAYOUT_QUERY)?.matches)
      window.scrollTo({ top: 0, behavior: "instant" });
  }, [panel]);
  return [panel, setPanel] as const;
}
