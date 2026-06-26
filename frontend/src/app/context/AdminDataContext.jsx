import React, { createContext, useContext } from "react";
import { useLocation } from "react-router-dom";
import { useToast } from "../hooks/useToast";
import { useAdminData } from "../hooks/useAdminData";
import { useAuth } from "../hooks/useAuth";

const AdminDataContext = createContext(null);

export function AdminDataProvider({ children }) {
  const location = useLocation();
  const { toast, showToast } = useToast();
  const { loading, refresh, refreshVersion } = useAdminData(showToast, location.pathname);
  const { logout: handleLogout } = useAuth();

  const value = {
    loading,
    refresh,
    refreshVersion,
    handleLogout,
    toast, showToast,
  };

  return (
    <AdminDataContext.Provider value={value}>
      {children}
    </AdminDataContext.Provider>
  );
}

export function useAdminDataContext() {
  const ctx = useContext(AdminDataContext);
  if (!ctx) throw new Error("useAdminDataContext must be used within AdminDataProvider");
  return ctx;
}
