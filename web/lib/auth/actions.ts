"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE } from "./session";

/** People sign in with Google (`app/auth/google`); signing out just ends the session here. */
export async function logout() {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
