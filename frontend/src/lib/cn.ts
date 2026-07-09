import { clsx, type ClassValue } from "clsx";

/** className 조건부 병합 헬퍼. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}
