import { useCallback, useEffect, useState } from "react";

export function useAdminData(_showToast, pathname = "/dashboard") {
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    setRefreshVersion((version) => version + 1);
  }, [pathname]);

  const refresh = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  return {
    loading: false,
    refresh,
    refreshVersion,
  };
}
