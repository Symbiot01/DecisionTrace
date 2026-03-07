import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import Dashboard from "@/pages/Dashboard";
import AskPage from "@/pages/AskPage";
import SearchPage from "@/pages/SearchPage";
import GraphExplorer from "@/pages/GraphExplorer";
import DecisionsPage from "@/pages/DecisionsPage";
import ContributorsPage from "@/pages/ContributorsPage";
import EntityDetailPage from "@/pages/EntityDetailPage";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/graph" element={<GraphExplorer />} />
            <Route path="/decisions" element={<DecisionsPage />} />
            <Route path="/contributors" element={<ContributorsPage />} />
            <Route path="/entity/*" element={<EntityDetailPage />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
