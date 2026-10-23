type CreationMode = "image_edit" | "text_to_image" | "batch_generate" | "batch_edit";

/** Wide feature illustration: source → result, distinct from compact menu icons. */
export function CreationProcessIcon({ mode }: { mode: CreationMode }) {
  const batch = mode === "batch_generate" || mode === "batch_edit";
  const textInput = mode === "text_to_image" || mode === "batch_generate";
  return (
    <svg className="creation-process-icon" viewBox="0 0 120 48" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <rect x="1" y="4" width="38" height="40" rx="11" fill="currentColor" fillOpacity=".06" strokeOpacity=".16" />
      <rect x="81" y="4" width="38" height="40" rx="11" fill="currentColor" fillOpacity=".17" strokeOpacity=".25" />
      {batch && <path d="M9 29V14a2 2 0 0 1 2-2h15M89 29V14a2 2 0 0 1 2-2h15" opacity=".5" />}
      {textInput ? (
        <g opacity=".75">
          <rect x="12" y="16" width="18" height="18" rx="3" />
          <path d="M17 21h8m-4 0v8m-2 0h4" />
        </g>
      ) : (
        <g opacity=".65">
          <rect x="12" y="16" width="18" height="18" rx="3" />
          <circle cx="25" cy="21" r="1.3" fill="currentColor" stroke="none" />
          <path d="m12 29 5-6 7 8 3-3 3 3" />
        </g>
      )}
      <path d="M48 24h23m-5-5 5 5-5 5" strokeWidth="1.8" />
      <rect x="92" y="16" width="18" height="18" rx="3" fill="currentColor" fillOpacity=".08" />
      <path d="m92 29 5-6 7 8 3-3 3 3" />
      <path d="M107 12v8m-4-4h8" strokeWidth="1.8" />
    </svg>
  );
}
