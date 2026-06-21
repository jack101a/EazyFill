import { useCallback } from 'react';
import { apiPost } from '../../api/client';

export function useAuth() {
  const logout = useCallback(async () => {
    try {
      await apiPost("/admin/logout", {});
    } finally {
      window.location.assign("/admin/login");
    }
  }, []);

  return { logout };
}
