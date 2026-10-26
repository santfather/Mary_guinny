import { useEffect, useState } from "react";

export type Route =
  | { name: "characters" }
  | { name: "character"; id: string }
  | { name: "locations" }
  | { name: "props" };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#\/?/, "").replace(/\/+$/, "");
  const [head, id] = path.split("/");
  if (head === "characters" && id) return { name: "character", id };
  if (head === "locations") return { name: "locations" };
  if (head === "props") return { name: "props" };
  return { name: "characters" };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}

export function navigate(hash: string): void {
  window.location.hash = hash;
}
