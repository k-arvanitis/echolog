"use client";

import React, { createContext, useContext, useState, useCallback, useRef } from "react";

interface Toast {
  id: number;
  message: string;
  type: "error" | "info" | "success";
}

interface ToastCtx {
  addToast: (message: string, type?: Toast["type"]) => void;
}

const ToastContext = createContext<ToastCtx>({ addToast: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const addToast = useCallback((message: string, type: Toast["type"] = "error") => {
    const id = ++counter.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const colorMap: Record<Toast["type"], string> = {
    error: "border-red-200 bg-red-50 text-red-800",
    info: "border-ink-200 bg-surface text-ink-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  };

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed right-4 top-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`rounded-md border px-3 py-2 text-sm ${colorMap[t.type]}`}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
