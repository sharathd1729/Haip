import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    user: {
      id: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      role: string;
      tenantId: string;
    };
  }

  interface User {
    id: string;
    role: string;
    tenantId: string;
    accessToken?: string;
    refreshToken?: string;
    /** "Keep me signed in" — defaults to true when omitted. */
    remember?: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
    role?: string;
    tenantId?: string;
    accessToken?: string;
    refreshToken?: string;
    /** "Keep me signed in" — see auth.ts's jwt callback. */
    remember?: boolean;
    /** ms epoch hard cutoff for remember=false sessions; undefined when remembered. */
    hardExpiry?: number;
  }
}
