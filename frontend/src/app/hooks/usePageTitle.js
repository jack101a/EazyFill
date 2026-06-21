import { useEffect } from "react";

export function usePageTitle(title) {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title ? `${title} | EazyFill Console` : "EazyFill Console";
    return () => {
      document.title = previousTitle;
    };
  }, [title]);
}
