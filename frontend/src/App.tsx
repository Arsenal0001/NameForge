import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { CatalogTable } from "@/components/catalog/CatalogTable";
import { CategoryMapping } from "@/components/categories/CategoryMapping";
import { MainDashboard } from "@/components/dashboard/MainDashboard";
import { TemplateBuilder } from "@/components/templates/TemplateBuilder";
import { AppShell } from "@/components/layout/AppShell";
import { Toaster } from "@/components/ui/sonner";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<MainDashboard />} />
            <Route path="catalog" element={<CatalogTable />} />
            <Route path="categories" element={<CategoryMapping />} />
            <Route path="templates" element={<TemplateBuilder />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster />
      </QueryClientProvider>
    </BrowserRouter>
  );
}
