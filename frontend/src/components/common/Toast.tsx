"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { AlertCircle, CheckCircle, Info } from "lucide-react";
import { cn } from "@/lib/cn";

type ToastType = "success" | "info" | "error";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TYPE_META: Record<
  ToastType,
  { icon: typeof CheckCircle; className: string }
> = {
  success: { icon: CheckCircle, className: "text-emerald-600 bg-emerald-50" },
  info: { icon: Info, className: "text-indigo-600 bg-indigo-50" },
  error: { icon: AlertCircle, className: "text-rose-600 bg-rose-50" },
};

/** 전역 토스트 provider — 루트 레이아웃 하위에서 앱을 감싼다. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, type: ToastType = "success") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2.5 items-end">
        {items.map((t) => {
          const meta = TYPE_META[t.type];
          const Icon = meta.icon;
          return (
            <div
              key={t.id}
              className="screen-enter flex items-center gap-3 bg-white/95 backdrop-blur-md shadow-float rounded-xl pl-3 pr-4 py-3 border border-slate-200/80 min-w-[280px]"
            >
              <span
                className={cn(
                  "grid place-items-center w-8 h-8 rounded-lg",
                  meta.className,
                )}
              >
                <Icon className="w-4 h-4" />
              </span>
              <span className="text-sm font-semibold text-slate-800">
                {t.message}
              </span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/** 토스트 트리거 훅. Provider 밖에서 호출하면 no-op(개발 편의). */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return { toast: () => {} };
  }
  return ctx;
}
