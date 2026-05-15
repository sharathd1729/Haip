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
      onboarding_step: number;
    };
  }

  interface User {
    id: string;
    role: string;
    tenantId: string;
    onboarding_step?: number;
    onboardingStep?: number;
    accessToken?: string;
    refreshToken?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
    role?: string;
    tenantId?: string;
    onboardingStep?: number;
    accessToken?: string;
    refreshToken?: string;
  }
}
