import React, { createContext, useContext, useState } from "react";
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

  const [createdKeyModal, setCreatedKeyModal] = useState({ open: false, keyId: null, keyValue: "", warnings: [] });
  const handleCopyKey = async (value) => {
    if (!value) return;
    await navigator.clipboard?.writeText(value);
    showToast("API key copied");
  };

  const value = {
    loading,
    refresh,
    refreshVersion,
    handleLogout,
    toast, showToast,
    createdKeyModal, setCreatedKeyModal,
    keyHandlers: { handleCopyKey },
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
