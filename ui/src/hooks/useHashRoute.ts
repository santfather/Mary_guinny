import { useEffect, useState } from "react";

import type { LibraryKind } from "../api/types";

export type Route =
  | { name: "characters" }
  | { name: "character"; id: string }
  | { name: "locations" }
  | { name: "location"; id: string }
  | { name: "props" }
  | { name: "prop"; id: string }
  | { name: "shots" }
  | { name: "shot"; id: string }
  | { name: "series"; id: string };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#\/?/, "").replace(/\/+$/, "");
  const [head, id] = path.split("/");
  if (head === "characters" && id) return { name: "character", id };
  if (head === "locations" && id) return { name: "location", id };
  if (head === "locations") return { name: "locations" };
  if (head === "props" && id) return { name: "prop", id };
  if (head === "props") return { name: "props" };
  if (head === "shots" && id) return { name: "shot", id };
  if (head === "shots") return { name: "shots" };
  if (head === "series" && id) return { name: "series", id };
  return { name: "characters" };
}

export function libraryKindOf(route: Route): LibraryKind | null {
  if (route.name === "locations" || route.name === "location") return "location";
  if (route.name === "props" || route.name === "prop") return "prop";
  return null;
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
