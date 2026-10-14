import { useEffect, useState } from "react";
import { Alert, Empty, Input, Modal, Pagination, Spin } from "antd";
import { callHost } from "@/integration/bridge";
import { rememberImage } from "@/integration/runtime";
import type { CanvasAsset } from "@/integration/protocol";

export type InsertAssetPayload = { kind: "text"; content: string; title: string } | { kind: "image"; dataUrl: string; title: string; storageKey?: string } | { kind: "video"; url: string; title: string; storageKey?: string; width?: number; height?: number };
type Props = { open: boolean; defaultTab?: string; onInsert: (payload: InsertAssetPayload) => void; onClose: () => void };

export function AssetPickerModal({ open, onInsert, onClose }: Props) {
    return <Modal title="从素材库添加" open={open} onCancel={onClose} footer={null} width={860} destroyOnHidden>
        {open && <HostMaterialsPanel onInsert={(payload) => { onInsert(payload); onClose(); }} />}
    </Modal>;
}

export function HostMaterialsPanel({ onInsert }: Pick<Props, "onInsert">) {
    const open = true;
    const [page, setPage] = useState(1);
    const [keyword, setKeyword] = useState("");
    const [items, setItems] = useState<(CanvasAsset & { title: string })[]>([]);
    const [total, setTotal] = useState(0);
    const [pageSize, setPageSize] = useState(20);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    useEffect(() => {
        if (!open) return;
        let ignore = false;
        setLoading(true); setError("");
        callHost("assets.list", { page, keyword }).then((result) => {
            if (ignore) return;
            result.items.forEach(rememberImage);
            setItems(result.items); setTotal(result.total); setPageSize(result.pageSize);
        }).catch((cause) => { if (!ignore) setError(cause.message); }).finally(() => { if (!ignore) setLoading(false); });
        return () => { ignore = true; };
    }, [open, page, keyword]);
    return <div className="p-3">
        <Input.Search aria-label="搜索素材" placeholder="搜索素材名称" onSearch={(value) => { setKeyword(value); setPage(1); }} className="mb-4" />
        {error ? <Alert type="error" title={error} /> : <Spin spinning={loading}>
            <div className="grid min-h-40 grid-cols-2 gap-3">
                {items.map((asset) => <button key={asset.id} type="button" className="overflow-hidden rounded-xl border border-border text-left hover:border-primary focus-visible:outline-2" onClick={() => { onInsert({ kind: "image", dataUrl: asset.url, title: asset.title }); }}>
                    <img src={asset.url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                    <span className="block truncate p-2 text-sm">{asset.title}</span>
                </button>)}
            </div>
            {!loading && !items.length && <Empty description="素材库还没有图片，可直接拖入图片到画布" />}
        </Spin>}
        <Pagination className="mt-4" current={page} pageSize={pageSize} total={total} onChange={setPage} showSizeChanger={false} hideOnSinglePage />
    </div>;
}
