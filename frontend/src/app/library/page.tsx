import { AppShell } from "@/components/common/AppShell";
import { LibraryScreen } from "@/components/library/LibraryScreen";

export default function LibraryPage() {
  return (
    <AppShell contextLabel="리포트 보관함">
      <LibraryScreen />
    </AppShell>
  );
}
