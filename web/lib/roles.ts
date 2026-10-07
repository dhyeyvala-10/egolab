import type { GrantableRole } from "@/lib/api/types";

/** What the admin can give someone (admin itself is the owner's alone). */
export const ROLE_CHOICES: { value: GrantableRole; label: string; help: string }[] = [
  { value: "pending", label: "No access", help: "Signed in, sees nothing" },
  { value: "viewer", label: "Viewer", help: "Can look, can't change anything or upload" },
  { value: "annotator", label: "Annotator", help: "Uploads and annotates" },
  { value: "reviewer", label: "Reviewer", help: "Annotates, reviews, and assigns work" },
];
