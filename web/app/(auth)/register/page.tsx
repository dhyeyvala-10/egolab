import { redirect } from "next/navigation";

/** Accounts are made by signing in with Google; old links to registration go to sign-in. */
export default function RegisterPage() {
  redirect("/login");
}
