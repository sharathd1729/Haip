"use client";
// Yaad sign-in: the shared sign-in form with Yaad's words; lands on the Calls screen.
import { Suspense } from "react";
import { LoginForm, type LoginBrand } from "@/components/auth/LoginForm";

const YAAD: LoginBrand = {
  title: "Welcome back",
  subtitle: "Sign in to see your calls and reminders",
  signupPrompt: "New to Yaad?",
  signupLabel: "Create your account",
  signupHref: "/yaad/signup",
  defaultCallback: "/dashboard/me",
};

export default function YaadLoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm brand={YAAD} />
    </Suspense>
  );
}
