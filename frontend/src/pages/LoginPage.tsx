import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

// Frappe accepts email OR username (e.g. Administrator on dev) — don't over-validate.
const loginSchema = z.object({
  email: z.string().min(1, 'Email or username is required'),
  password: z.string().min(1, 'Password is required'),
});

type LoginForm = z.infer<typeof loginSchema>;

export default function LoginPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [authError, setAuthError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setAuthError(null);
    try {
      await client.login(values.email, values.password);
      // first login without a workspace → onboarding wizard
      const status = await client.onboardingStatus().catch(() => null);
      await navigate(status && !status.has_workspace ? '/onboarding' : '/inbox');
    } catch {
      setAuthError('Login failed — check your email and password.');
    }
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">WaveDesk</CardTitle>
          <CardDescription>Sign in to your workspace</CardDescription>
        </CardHeader>
        <form onSubmit={(e) => void onSubmit(e)} noValidate>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="email">Email or username</Label>
              <Input
                id="email"
                type="text"
                placeholder="you@company.com"
                autoComplete="username"
                {...register('email')}
              />
              {errors.email && (
                <p role="alert" className="text-sm text-destructive">
                  {errors.email.message}
                </p>
              )}
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register('password')}
              />
              {errors.password && (
                <p role="alert" className="text-sm text-destructive">
                  {errors.password.message}
                </p>
              )}
            </div>
          </CardContent>
          <CardFooter className="flex-col gap-2">
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              Sign in
            </Button>
            {authError && (
              <p role="alert" className="text-sm text-destructive">
                {authError}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              New to WaveDesk?{' '}
              <Link to="/signup" className="text-primary underline-offset-2 hover:underline">
                Create an account
              </Link>
              {' · '}
              <Link to="/pricing" className="text-primary underline-offset-2 hover:underline">
                Pricing
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
