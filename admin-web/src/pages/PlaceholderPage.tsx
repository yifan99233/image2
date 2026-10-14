import { LockKeyhole } from "lucide-react";

export function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="state-panel">
      <LockKeyhole size={28} />
      <h2>{title}</h2>
      <p>该模块将在后续任务包中实现，当前 AW-01 已预留路由、菜单权限和布局承载区域。</p>
    </section>
  );
}
