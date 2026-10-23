import { useId, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

export function ExpandablePrompt({ text }: { text: string }) {
  const id = useId();
  const previewRef = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const element = previewRef.current;
    if (!element || expanded) return;
    const measure = () => setOverflows(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, expanded]);

  return (
    <div className="work-prompt">
      <p ref={previewRef} id={id} className={`work-prompt__text${expanded ? " is-expanded" : ""}`}>{text}</p>
      {(overflows || expanded) && (
        <button className="work-prompt__toggle" type="button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded((value) => !value)}>
          {expanded ? "收起" : "展开"}
          <ChevronDown size={14} />
        </button>
      )}
    </div>
  );
}
