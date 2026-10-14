import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search, Sparkles, X } from "lucide-react";
import type { ImageModel } from "@/types/api";

type ModelPickerProps = {
  models: ImageModel[];
  selectedModelId: number | null;
  onChange: (model: ImageModel) => void;
  label?: string;
  triggerClassName?: string;
  isLoading?: boolean;
  disabled?: boolean;
};

type ModelFilter = "recommended" | "all";

const modelStateLabels = (model: ImageModel) => {
  const labels: string[] = [];
  if (model.is_recommended) labels.push("推荐");
  if (model.is_new) labels.push("NEW");
  if (model.is_stable) labels.push("稳定");
  return labels;
};

const matchesModelQuery = (model: ImageModel, query: string) => {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return true;
  return [model.name, model.code, model.description]
    .filter(Boolean)
    .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
};

const rankModels = (models: ImageModel[]) =>
  [...models].sort((left, right) => {
    if (left.is_recommended !== right.is_recommended) return left.is_recommended ? -1 : 1;
    if (left.is_new !== right.is_new) return left.is_new ? -1 : 1;
    if (left.is_stable !== right.is_stable) return left.is_stable ? -1 : 1;
    return left.name.localeCompare(right.name, "zh-CN");
  });

/**
 * A shared generation-model picker.  The catalog fields shown here map only
 * to the verified ImageModel contract, so every creation surface explains the
 * same capabilities without inventing model-specific copy.
 */
export const ModelPicker = ({
  models,
  selectedModelId,
  onChange,
  label = "生成模型",
  triggerClassName,
  isLoading = false,
  disabled = false,
}: ModelPickerProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<ModelFilter>("recommended");
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );
  const recommendedModels = useMemo(() => models.filter((model) => model.is_recommended), [models]);
  const filteredModels = useMemo(() => {
    const candidateModels = filter === "recommended" && recommendedModels.length ? recommendedModels : models;
    return rankModels(candidateModels.filter((model) => matchesModelQuery(model, query)));
  }, [filter, models, query, recommendedModels]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };
    const focusTimer = window.setTimeout(() => searchInputRef.current?.focus(), 0);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const openPicker = () => {
    if (disabled || isLoading || !models.length) return;
    setFilter(recommendedModels.length ? "recommended" : "all");
    setQuery("");
    setIsOpen(true);
  };

  const selectModel = (model: ImageModel) => {
    onChange(model);
    setIsOpen(false);
  };

  return (
    <>
      <button
        type="button"
        className={`model-picker__trigger ${triggerClassName ?? ""}`.trim()}
        onClick={openPicker}
        disabled={disabled || isLoading || !models.length}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
      >
        <Sparkles size={15} aria-hidden />
        <span className="model-picker__trigger-label">
          {isLoading ? "加载模型中" : selectedModel?.name ?? "选择模型"}
        </span>
        <ChevronDown size={15} aria-hidden />
      </button>

      {isOpen
        ? createPortal(
            <div className="model-picker__backdrop" role="presentation" onMouseDown={() => setIsOpen(false)}>
              <section
                className="model-picker__dialog"
                role="dialog"
                aria-modal="true"
                aria-label={label}
                onMouseDown={(event) => event.stopPropagation()}
              >
                <header className="model-picker__header">
                  <div>
                    <p>{label}</p>
                    <h2>选择最适合当前任务的模型</h2>
                  </div>
                  <button type="button" className="model-picker__close" onClick={() => setIsOpen(false)} aria-label="关闭模型选择">
                    <X size={18} />
                  </button>
                </header>

                <div className="model-picker__controls">
                  <div className="model-picker__search">
                    <Search size={16} aria-hidden />
                    <input
                      ref={searchInputRef}
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="搜索模型名称或说明"
                      aria-label="搜索模型"
                    />
                  </div>
                  <div className="model-picker__filters" role="tablist" aria-label="模型范围">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={filter === "recommended"}
                      className={filter === "recommended" ? "is-active" : ""}
                      disabled={!recommendedModels.length}
                      onClick={() => setFilter("recommended")}
                    >
                      推荐
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={filter === "all"}
                      className={filter === "all" ? "is-active" : ""}
                      onClick={() => setFilter("all")}
                    >
                      全部 {models.length}
                    </button>
                  </div>
                </div>

                <div className="model-picker__list" role="listbox" aria-label="可用模型">
                  {filteredModels.map((model) => {
                    const isSelected = model.id === selectedModelId;
                    const stateLabels = modelStateLabels(model);
                    return (
                      <button
                        key={model.id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        className={`model-picker__option ${isSelected ? "is-selected" : ""}`}
                        onClick={() => selectModel(model)}
                      >
                        <div className="model-picker__option-head">
                          <div>
                            <strong>{model.name}</strong>
                            {model.description ? <p>{model.description}</p> : null}
                          </div>
                          {isSelected ? <Check size={18} aria-label="当前选择" /> : null}
                        </div>
                        <div className="model-picker__badges">
                          {stateLabels.map((stateLabel) => (
                            <span className="model-picker__state" key={stateLabel}>{stateLabel}</span>
                          ))}
                          <span className="model-picker__spec">最多 {model.max_input_images} 张输入图</span>
                          <span className="model-picker__spec">{model.supported_aspect_ratios.length} 种画幅</span>
                          <span className="model-picker__spec">{model.supported_resolutions.length} 档清晰度</span>
                          {model.supported_durations?.length ? <span className="model-picker__spec">{model.supported_durations.length} 档时长</span> : null}
                        </div>
                        {model.speed_hint || model.risk_hint ? (
                          <div className="model-picker__notes">
                            {model.speed_hint ? <span>{model.speed_hint}</span> : null}
                            {model.risk_hint ? <span>{model.risk_hint}</span> : null}
                          </div>
                        ) : null}
                      </button>
                    );
                  })}
                  {!filteredModels.length ? <p className="model-picker__empty">没有匹配的模型，试试切换到“全部”或修改关键词。</p> : null}
                </div>
              </section>
            </div>,
            document.body,
          )
        : null}
    </>
  );
};
