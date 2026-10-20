// src/useRoute.ts
//
// React binding of the hash router in route.ts: the current Route follows `location.hash`
// (so reload, bookmarks and the browser's back button work), and `navigate` changes it.

import { useCallback, useEffect, useState } from "react";

import { formatHash, parseHash, type Route } from "./route";

/** Moves to another route; `replace` rewrites the current history entry instead of adding one. */
export type Navigate = (route: Route, replace?: boolean) => void;

/** The current route plus a function to change it. */
export function useRoute(): [Route, Navigate] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback<Navigate>((next, replace = false) => {
    const hash = formatHash(next);
    if (replace) {
      // replaceState does not fire "hashchange", so the state is set here.
      window.history.replaceState(null, "", hash);
      setRoute(next);
    } else {
      window.location.hash = hash;
    }
  }, []);

  return [route, navigate];
}
