// Why a request to scrap failed, in a few words for a toast or a line: the server's own
// message, that the login in front of scrap has expired (api.ts LoginExpired), or, when it
// was not reached at all, what the caller says (by default "can't reach the server").
import { ApiError, LoginExpired } from "./api";

export const why = (err: unknown, unreached = "can't reach the server") =>
  err instanceof ApiError || err instanceof LoginExpired ? err.message : unreached;
