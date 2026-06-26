import React, { Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { DashboardLayout } from "./layout/DashboardLayout";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { AdminDataProvider, useAdminDataContext } from "./context/AdminDataContext";
import { useThemeContext } from "./context/ThemeContext";
import { COMPATIBILITY_REDIRECTS } from "./navigation";

const EazyFillOverviewPage = React.lazy(() => import("./features/overview/EazyFillOverviewPage").then((module) => ({ default: module.EazyFillOverviewPage })));
const OperationsPage = React.lazy(() => import("./features/operations/OperationsPage").then((module) => ({ default: module.OperationsPage })));
const BackupsPage = React.lazy(() => import("./features/backups/BackupsPage").then((module) => ({ default: module.BackupsPage })));
const UsersPanel = React.lazy(() => import("./components/UsersPanel").then((module) => ({ default: module.UsersPanel })));
const PlansPanel = React.lazy(() => import("./components/PlansPanel").then((module) => ({ default: module.PlansPanel })));
const PaymentsPanel = React.lazy(() => import("./components/PaymentsPanel").then((module) => ({ default: module.PaymentsPanel })));
const ExtensionHealthPanel = React.lazy(() => import("./components/ExtensionHealthPanel").then((module) => ({ default: module.ExtensionHealthPanel })));
const CaptchaModelsPage = React.lazy(() => import("./features/captcha/CaptchaModelsPage").then((module) => ({ default: module.CaptchaModelsPage })));

function AppRoutes() {
  const context = useAdminDataContext();
  const { isDark } = useThemeContext();

  return (
    <DashboardLayout
      handleLogout={context.handleLogout}
      loading={context.loading}
      toast={context.toast}
    >
      <Suspense fallback={<div className="flex items-center justify-center py-20"><div className={`h-8 w-8 animate-spin rounded-full border-2 border-t-transparent ${isDark ? "border-[#FF5FB8]" : "border-[#8B5CF6]"}`} /></div>}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<EazyFillOverviewPage />} />
          <Route path="/users" element={<UsersPanel showToast={context.showToast} />} />
          <Route path="/plans" element={<PlansPanel showToast={context.showToast} />} />
          <Route path="/payments" element={<PaymentsPanel showToast={context.showToast} />} />
          <Route path="/operations" element={<OperationsPage />} />
          <Route path="/backups" element={<BackupsPage />} />
          <Route path="/extension-health" element={<ExtensionHealthPanel showToast={context.showToast} />} />
          <Route path="/captcha-models" element={<CaptchaModelsPage showToast={context.showToast} />} />

          {COMPATIBILITY_REDIRECTS.map(({ from, to }) => (
            <Route key={from} path={from} element={<Navigate to={to} replace />} />
          ))}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </DashboardLayout>
  );
}

export function App() {
  return (
    <ErrorBoundary>
      <ConfirmProvider>
        <AdminDataProvider>
          <AppRoutes />
        </AdminDataProvider>
      </ConfirmProvider>
    </ErrorBoundary>
  );
}

export default App;
