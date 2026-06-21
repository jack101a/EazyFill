import { useState, useCallback, useRef } from 'react';

export function useToast() {
  const [toast, setToast] = useState({ message: "", type: "" });
  const timeoutRef = useRef(null);

  const showToast = useCallback((message, type = "success") => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setToast({ message, type });
    timeoutRef.current = setTimeout(() => {
      setToast({ message: "", type: "" });
      timeoutRef.current = null;
    }, 3000);
  }, []);

  return { toast, showToast };
}
