import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useSession } from "./session";

/** Cached query results must never outlive the session that fetched them: query keys carry no user
 *  or business, so without this a second user on the same tab would briefly see the first user's data.
 *  Clears the whole cache whenever the signed-in identity changes (sign-out, expiry, or a new login). */
export function CacheGuard() {
  const { token, username } = useSession();
  const qc = useQueryClient();
  const identity = `${token ?? ""}|${username ?? ""}`;
  const previous = useRef(identity);
  useEffect(() => {
    if (previous.current !== identity) {
      qc.clear();
      previous.current = identity;
    }
  }, [identity, qc]);
  return null;
}
