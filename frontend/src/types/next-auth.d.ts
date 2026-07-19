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
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
    role?: string;
    tenantId?: string;
    accessToken?: string;
    refreshToken?: string;
  }
}
