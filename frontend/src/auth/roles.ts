import type { Role } from "../api/types";

/** Analysts and admins may act; viewers are read-only. The server stays the authority (403). */
export const canAct = (role: Role | null): boolean => role === "analyst" || role === "admin";
