import { useLocation } from "react-router-dom";

export const PlaceholderPage = () => {
  const location = useLocation();

  return (
    <main className="placeholder-page">
      <p className="eyebrow">未找到页面</p>
      <h1>这个地址没有匹配的功能页</h1>
      <p>{location.pathname} 不在当前用户端路由表中。请从左侧菜单进入已接入的真实页面。</p>
    </main>
  );
};
