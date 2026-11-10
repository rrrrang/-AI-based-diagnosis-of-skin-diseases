
/* 역할: React 애플리케이션 실행 */
// React 및 ReactDOM 불러오기
import React from "react";
import ReactDOM from "react-dom/client";

import { HashRouter } from "react-router-dom";  // 주소에 #을 사용하는 라우터
import App from "./App";                        // 전체 애플리케이션
import "./index.css";                           // 전체 기본 CSS

// HTML의 root 영역에 React 연결
ReactDOM.createRoot(
  document.getElementById("root")!
).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
);
