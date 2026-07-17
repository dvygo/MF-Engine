// Demo logins read straight from NEXT_PUBLIC_* env vars.
//
// WARNING — a speed bump, not access control. These values are compiled into
// the client bundle (that's what NEXT_PUBLIC_ means), so the passwords are
// readable via View Source, and /public/data/*.json can be fetched without
// logging in at all. The ALLOWED_TYPE rules below only shape what the UI
// renders; they do not stop anyone determined. Real gating needs the shards
// moved out of /public and filtered by a server route against a session.

export type User = {
  email: string;
  /** "*" = every record kind, else MANAGERS | FIRMS */
  allowedType: string;
  /** "*" = every SEBI type, else a list of MF | PMS | AIF | RIA */
  allowedType2: string[];
};

// Next.js inlines NEXT_PUBLIC_* at build time only for statically analysable
// lookups, so each var is written out literally rather than built from a loop.
const ENV_USERS = [
  {
    email: process.env.NEXT_PUBLIC_USER1_EMAIL,
    pass: process.env.NEXT_PUBLIC_USER1_PASS,
    type: process.env.NEXT_PUBLIC_USER1_ALLOWED_TYPE,
    type2: process.env.NEXT_PUBLIC_USER1_ALLOWED_TYPE2,
  },
  {
    email: process.env.NEXT_PUBLIC_USER2_EMAIL,
    pass: process.env.NEXT_PUBLIC_USER2_PASS,
    type: process.env.NEXT_PUBLIC_USER2_ALLOWED_TYPE,
    type2: process.env.NEXT_PUBLIC_USER2_ALLOWED_TYPE2,
  },
  {
    email: process.env.NEXT_PUBLIC_USER3_EMAIL,
    pass: process.env.NEXT_PUBLIC_USER3_PASS,
    type: process.env.NEXT_PUBLIC_USER3_ALLOWED_TYPE,
    type2: process.env.NEXT_PUBLIC_USER3_ALLOWED_TYPE2,
  },
];

/** UI label -> the sebi_type slug the data actually uses. */
export const TYPE2_TO_SLUG: Record<string, string> = {
  MF: "mutual-funds",
  PMS: "portfolio-managers",
  AIF: "aif",
  RIA: "investment-advisers",
};

export function authenticate(email: string, pass: string): User | null {
  const e = email.trim().toLowerCase();
  const hit = ENV_USERS.find(
    (u) => u.email && u.email.toLowerCase() === e && u.pass === pass,
  );
  if (!hit) return null;
  const type2 = (hit.type2 ?? "*").trim();
  return {
    email: hit.email!,
    allowedType: (hit.type ?? "*").trim().toUpperCase(),
    allowedType2:
      type2 === "*"
        ? ["*"]
        : type2
            .split(",")
            .map((t) => t.trim().toUpperCase())
            .filter(Boolean),
  };
}

/** Does this user's ALLOWED_TYPE cover a row kind ("firm" | "manager")? */
export function allowsKind(user: User, kind: string): boolean {
  if (user.allowedType === "*") return true;
  if (user.allowedType === "MANAGERS") return kind === "manager";
  if (user.allowedType === "FIRMS") return kind === "firm";
  return false;
}

/** Does this user's ALLOWED_TYPE2 cover a row's sebi_type slug? */
export function allowsType2(user: User, slug: string | undefined): boolean {
  if (user.allowedType2.includes("*")) return true;
  if (!slug) return false;
  return user.allowedType2.some((t) => TYPE2_TO_SLUG[t] === slug);
}
