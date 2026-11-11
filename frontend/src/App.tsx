import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { Login } from "./auth/Login";
import { SessionProvider, useSession } from "./auth/session";
import { Shell } from "./components/Shell";
import { SourceProvider } from "./source";
import { GraphExplorer } from "./pages/GraphExplorer";
import { Investigation } from "./pages/Investigation";
import { Investigator } from "./pages/Investigator";
import { LiveMonitoring } from "./pages/LiveMonitoring";
import { Overview } from "./pages/Overview";

function Protected() {
  const { token } = useSession();
  return token ? <Shell /> : <Navigate to="/login" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route index element={<Overview />} />
        <Route path="live" element={<LiveMonitoring />} />
        <Route path="investigation" element={<Investigation />} />
        <Route path="investigation/:txnId" element={<Investigation />} />
        <Route path="graph" element={<GraphExplorer />} />
        <Route path="investigator" element={<Investigator />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

const queries = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

export default function App() {
  return (
    <QueryClientProvider client={queries}>
      <SessionProvider>
        <SourceProvider>
          <HashRouter><AppRoutes /></HashRouter>
        </SourceProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
