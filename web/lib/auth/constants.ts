/** httpOnly cookie holding the API access token. Shared by proxy.ts and server code. */
export const SESSION_COOKIE = "egolabs_session";

/** Request header proxy.ts sets so layouts know which page was requested. */
export const PATH_HEADER = "x-egolabs-path";
